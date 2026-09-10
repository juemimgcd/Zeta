from collections.abc import Sequence
from pathlib import Path

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ToolCall,
    ToolMessage,
)

from zeta.dispatch import execute_tool
from zeta.hooks import Decision, Hooks
from zeta.lifecycle import Event, Listener, emit, finish_event
from zeta.loop_common import RunStopped
from zeta.runtime_base import ModelIO, RunOptions, RunStatus, Runtime, ToolExecution
from zeta.tools import tool_outcome


class HookRuntime(Runtime):
    def __init__(
            self,
            workspace: Path,
            *,
            hooks: Hooks | None = None,
            listeners: Sequence[Listener] = (),
            io: ModelIO | None = None,
            options: RunOptions | None = None,
    ) -> None:
        super().__init__(workspace, io=io, options=options)
        self.hooks = hooks if hooks is not None else Hooks()
        self.listeners = listeners

    async def start(self, prompt: str | None) -> None:
        await super().start(prompt)
        await emit(Event("run_start"), self.listeners)

    async def begin_turn(self) -> None:
        await emit(Event("turn_start"), self.listeners)

    async def apply_before_model(
            self, messages: list[BaseMessage]
    ) -> list[BaseMessage]:
        view = await self.hooks.invoke("before_model", messages)
        if not isinstance(view, list):
            raise TypeError("missing model input")
        return view

    async def prepare(self) -> list[BaseMessage]:
        return await self.apply_before_model(await super().prepare())

    async def on_response(self, response: AIMessage) -> None:
        await super().on_response(response)
        await self.hooks.invoke("after_model", response)
        await emit(Event("model_response"), self.listeners)

    async def execute(self, call: ToolCall) -> ToolExecution:
        return await execute_tool(call, self.workspace, self.hooks, self.listeners)

    async def on_result(self, execution: ToolExecution) -> None:
        await super().on_result(execution)
        await emit(
            Event(
                "tool_end",
                tool_outcome(execution.result),
                execution.result.tool_call_id,
            ),
            self.listeners,
        )

    async def after_turn(self, results: list[ToolMessage]) -> None:
        await super().after_turn(results)
        await emit(Event("turn_end"), self.listeners)
        decision = await self.hooks.invoke("after_turn", self.history)
        if isinstance(decision, Decision) and decision.stop:
            raise RunStopped(decision.reason)

    async def finish(self, status: RunStatus, reason: str) -> None:
        await finish_event(f"{status}: {reason}", self.listeners)