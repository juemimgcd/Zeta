import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import BaseMessage, HumanMessage
from openai import APIError, APIStatusError

from zeta.compaction import CompactionError, compact
from zeta.context import (
    Budget,
    Resource,
    Summary,
    build_context,
    estimate_tokens,
)
from zeta.hooks import Hooks
from zeta.lifecycle import Listener
from zeta.loop import run_loop
from zeta.loop_common import (
    INSTRUCTIONS,
    ModelResponseError,
    RunLimitError,
    validate_history,
)
from zeta.memory import Memory, MemoryStore, recall
from zeta.model_io import SUMMARY_MAX_TOKENS, request_once, summarize_once
from zeta.runtime_base import ModelIO, RequestFn, RunOptions, SummaryFn
from zeta.session import load_session, save_session
from zeta.session_runtime import SessionRuntime
from zeta.storage import JsonStore
from zeta.tools import tool_schemas


@dataclass
class Services:
    database: JsonStore
    memories: MemoryStore
    workspace: Path
    budget: Budget = field(default_factory=Budget)
    hooks: Hooks = field(default_factory=Hooks)
    listeners: Sequence[Listener] = ()
    resources: Sequence[Resource] = ()
    recall_query: str = ""
    request: RequestFn = request_once
    summarizer: SummaryFn = summarize_once


def read_summary(services: Services, session_id: str) -> Summary | None:
    body = services.database.get("summary", session_id)
    if body is None:
        return None
    summary = Summary.model_validate_json(body)
    for memory_id in summary.memory_ids:
        record = services.database.get("memory", memory_id)
        memory = None if record is None else Memory.model_validate_json(record)
        if (
            memory is None
            or not memory.active
            or memory.scope not in services.memories.allowed_scopes
        ):
            raise ValueError(
                "summary uses forgotten/inaccessible memory; start a fresh session"
            )
    return summary


class ContextRuntime(SessionRuntime):
    def __init__(self, session_id: str, services: Services) -> None:
        super().__init__(
            services.database,
            session_id,
            services.workspace,
            allowed_scopes=services.memories.allowed_scopes,
            hooks=services.hooks,
            listeners=services.listeners,
            io=ModelIO(request=services.request, summarize=services.summarizer),
            options=RunOptions(output_tokens=services.budget.output),
        )
        self.services = services
        self.query = services.recall_query
        self.force_compaction = False
        self.overflow_retried = False
        self.summary_calls = 0
        self.compaction_note = ""

    async def start(self, prompt: str | None) -> None:
        await super().start(prompt)
        self.query = self.services.recall_query or prompt or ""

    async def prepare(self) -> list[BaseMessage]:
        services = self.services
        session = load_session(self.database, self.session_id)
        memories = recall(services.memories, self.query, self.allowed_scopes)
        with self.database.transaction():
            session.memory_ids = sorted(
                set(session.memory_ids) | {memory.id for memory in memories}
            )
            save_session(self.database, session)
        summary = read_summary(services, self.session_id)
        base_session = session.model_dump_json()
        base_summary = self.database.get("summary", self.session_id)
        schema_tokens = estimate_tokens(
            [HumanMessage(content=json.dumps(tool_schemas(), ensure_ascii=False))]
        )
        if schema_tokens > services.budget.tools:
            raise RunLimitError("tool schemas exceed reserved allowance")
        # Evaluate compaction on the same mandatory projection on both sides.
        view = build_context(
            INSTRUCTIONS, (), (), summary, session.entries, services.budget
        )
        if self.force_compaction or view.needs_compaction:
            fixed_tokens = estimate_tokens([HumanMessage(content=INSTRUCTIONS)])
            keep_tokens = max(
                1,
                min(
                    6000,
                    int(services.budget.input_limit * 0.65)
                    - fixed_tokens
                    - SUMMARY_MAX_TOKENS
                    - 256,
                ),
            )

            async def summarize_counted(prompt: str) -> str:
                if self.summary_calls >= 4:
                    raise CompactionError("run summary allowance exhausted")
                self.summary_calls += 1
                return await self.io.summarize(prompt)

            try:
                candidate = await compact(
                    session.entries,
                    summary,
                    summarize_counted,
                    budget=services.budget,
                    memory_ids=session.memory_ids,
                    keep_tokens=keep_tokens,
                    max_calls=4 - self.summary_calls,
                )
                candidate_view = build_context(
                    INSTRUCTIONS, (), (), candidate, session.entries, services.budget
                )
                if (
                    candidate_view.estimated_tokens >= view.estimated_tokens
                    or candidate_view.estimated_tokens > services.budget.input_limit
                ):
                    raise CompactionError(
                        "candidate is not smaller or still exceeds allowance"
                    )
            except (CompactionError, ModelResponseError, APIError) as error:
                if (
                    self.force_compaction
                    or view.estimated_tokens > services.budget.input_limit
                ):
                    raise
                self.compaction_note = f"kept original context: {type(error).__name__}"
            else:
                # No await between rechecking the snapshot and writing the candidate.
                with self.database.transaction():
                    if (
                        self.database.get("session", self.session_id) != base_session
                        or self.database.get("summary", self.session_id) != base_summary
                    ):
                        raise RunLimitError("session changed during compaction")
                    for memory_id in candidate.memory_ids:
                        body = self.database.get("memory", memory_id)
                        memory = (
                            None if body is None else Memory.model_validate_json(body)
                        )
                        if (
                            memory is None
                            or not memory.active
                            or memory.scope not in self.allowed_scopes
                        ):
                            raise RunLimitError(
                                "summary memory source became inaccessible"
                            )
                    self.database.put(
                        "summary", self.session_id, candidate.model_dump_json()
                    )
                summary = candidate
                self.force_compaction = False
                self.compaction_note = f"compacted {view.estimated_tokens} -> {candidate_view.estimated_tokens}"
        view = build_context(
            INSTRUCTIONS,
            services.resources,
            memories,
            summary,
            session.entries,
            services.budget,
        )
        request_view = await self.apply_before_model(view.messages)
        validate_history(request_view)
        if estimate_tokens(request_view) > services.budget.input_limit:
            raise RunLimitError("final model input exceeds allowance")
        return request_view

    async def retry(self, error: APIStatusError) -> bool:
        detail = str(error.body).casefold()
        overflow = error.status_code == 400 and any(
            marker in detail
            for marker in (
                "context_length_exceeded",
                "maximum context length",
                "context window",
            )
        )
        if not overflow or self.overflow_retried:
            return False
        self.overflow_retried = self.force_compaction = True
        return True


async def run_session_task(
    session_id: str,
    prompt: str | None,
    services: Services,
) -> str:
    runtime = ContextRuntime(session_id, services)
    return await run_loop(prompt, runtime)
