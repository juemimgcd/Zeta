from collections.abc import Sequence
from pathlib import Path

from langchain_core.messages import AIMessage

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
    load_resume_point,
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
            reviewed_resume: bool = False,
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
        self.reviewed_resume = reviewed_resume
        self.owns_run = False

    async def start(self, prompt: str | None) -> None:
        if self.started:
            raise ValueError("create a fresh Runtime to resume")
        point = load_resume_point(self.database, self.session_id)
        if point.session.scope not in self.allowed_scopes:
            raise PermissionError("session belongs to another scope")
        if point.action == "resolve_pending":
            raise ValueError("resolve pending calls explicitly")
        if prompt is not None:
            if point.action != "new_input":
                raise ValueError("finish or review the previous task first")
            append_user(self.database, self.session_id, prompt)
        else:
            if point.action == "new_input":
                raise ValueError("new user input is required")
            if point.action == "review" and not self.reviewed_resume:
                raise ValueError("explicit resume review required")
            if point.session.entries and isinstance(
                    decode(point.session.entries[-1]), AIMessage
            ):
                raise ValueError(
                    "review terminal hook failure; final answer already exists"
                )
            with self.database.transaction():
                session = load_session(self.database, self.session_id)
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