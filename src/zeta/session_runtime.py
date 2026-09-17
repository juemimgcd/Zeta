from collections.abc import Sequence
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from zeta.hook_runtime import HookRuntime
from zeta.hooks import Hooks
from zeta.lifecycle import Event, Listener, emit
from zeta.runtime_base import ModelIO, RunOptions, RunStatus, ToolExecution
from zeta.session import (
    append_user,
    commit_response,
    commit_tool_result,
    decode,
    finish_session,
    history_messages,
    load_session,
    save_session,
)
from zeta.storage import JsonStore


class SessionRuntime(HookRuntime):
    """Supplied adapter: persistence precedes HookRuntime's observation hooks."""

    def __init__(
        self,
        database: JsonStore,
        session_id: str,
        workspace: Path,
        *,
        allowed_scopes: frozenset[str],
        hooks: Hooks | None = None,
        listeners: Sequence[Listener] = (),
        io: ModelIO | None = None,
        options: RunOptions | None = None,
    ) -> None:
        super().__init__(
            workspace, hooks=hooks, listeners=listeners, io=io, options=options
        )
        self.database = database
        self.session_id = session_id
        self.allowed_scopes = allowed_scopes
        self.owns_run = False

    async def start(self, prompt: str | None) -> None:
        if self.started:
            raise ValueError("create a fresh Runtime to resume")
        session = load_session(self.database, self.session_id)
        if session.scope not in self.allowed_scopes:
            raise PermissionError("session belongs to another scope")
        if session.pending:
            raise ValueError(
                "uncommitted tool results; resolve them or create a new session"
            )
        if prompt is not None:
            append_user(self.database, self.session_id, prompt)
        else:
            # An explicit start(None) continues only an unfinished model request.
            if not session.entries or not isinstance(
                decode(session.entries[-1]), (HumanMessage, ToolMessage)
            ):
                raise ValueError(
                    "no unfinished request to resume; supply new input or create a new session"
                )
            with self.database.transaction():
                session.status, session.reason = "running", ""
                save_session(self.database, session)
        self.started = self.owns_run = True
        self.history = history_messages(
            load_session(self.database, self.session_id).entries
        )
        await emit(Event("run_start"), self.listeners)

    async def on_response(self, response: AIMessage) -> None:
        commit_response(self.database, self.session_id, response)
        await super().on_response(response)

    async def on_result(self, execution: ToolExecution) -> None:
        commit_tool_result(
            self.database, self.session_id, execution.result, execution.raw
        )
        await super().on_result(execution)

    async def finish(self, status: RunStatus, reason: str) -> None:
        try:
            if self.owns_run:
                finish_session(self.database, self.session_id, status, reason)
        finally:
            await super().finish(status, reason)
