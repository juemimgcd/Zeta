# ruff: noqa: F401  # Prepared imports for exercise bodies.
# pyright: reportUnusedImport=false
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from zeta.loop_common import validate_history

type HookName = Literal[
    "before_model", "after_model", "before_tool", "after_tool", "after_turn"
]


@dataclass(frozen=True)
class Decision:
    stop: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ToolContext:
    name: str
    call_id: str
    path: str


type HookContext = list[BaseMessage] | AIMessage | ToolContext | ToolMessage
type HookResult = list[BaseMessage] | ToolMessage | Decision | None
type Callback = Callable[[HookContext], Awaitable[HookResult]]


class Hooks:
    def __init__(self) -> None:
        self.callbacks: dict[HookName, list[Callback]] = {
            name: []
            for name in (
                "before_model",
                "after_model",
                "before_tool",
                "after_tool",
                "after_turn",
            )
        }

    def register(self, name: HookName, callback: Callback) -> None:
        if name not in self.callbacks:
            raise ValueError("unknown hook")
        self.callbacks[name].append(callback)

    async def invoke(self, name: HookName, context: HookContext) -> HookResult:
        if name not in self.callbacks:
            raise ValueError("unknown hook")
        current = deepcopy(context)
        for callback in self.callbacks[name]:
            result = await callback(deepcopy(current))
            if result is None:
                continue
            if name == "before_model":
                if not isinstance(current, list) or not isinstance(result, list):
                    raise TypeError("before_model must return a message list")
                if not current or len(result) < len(current):
                    raise ValueError("hook cannot remove the prepared context")
                if result[-len(current):] != current:
                    raise ValueError("hook cannot rewrite prepared messages")
                for message in result[: -len(current)]:
                    if (
                            not isinstance(message, HumanMessage)
                            or not isinstance(message.content, str)
                            or not message.content.strip()
                    ):
                        raise ValueError(
                            "hook may only prepend user-level context data"
                        )
                validate_history(result)
                current = deepcopy(result)
            elif name == "after_tool":
                if not isinstance(current, ToolMessage) or not isinstance(
                        result, ToolMessage
                ):
                    raise TypeError("after_tool must return a tool result")
                if (
                        result.name,
                        result.tool_call_id,
                        result.status,
                        result.artifact,
                ) != (
                        current.name,
                        current.tool_call_id,
                        current.status,
                        current.artifact,
                ):
                    raise ValueError("hook changed tool result identity or outcome")
                current = deepcopy(result)
            elif name in ("before_tool", "after_turn"):
                if not isinstance(result, Decision):
                    raise TypeError("decision hook must return Decision")
                if result.stop:
                    if not result.reason.strip():
                        raise ValueError("a stop/deny decision needs a reason")
                    return result
            else:
                raise TypeError("after_model is read-only and must return None")
        if name in ("before_tool", "after_turn"):
            return Decision()
        if name == "after_model":
            return None
        if isinstance(current, (list, ToolMessage)):
            return current
        raise TypeError("invalid hook context")
