# ruff: noqa: F401  # Prepared imports for exercise bodies.
# pyright: reportUnusedImport=false
import inspect
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
from pydantic_ai.mcp import ToolResult

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
                for message in result[-len(current):]:
                    if (
                        not isinstance(message,HumanMessage)
                        or not isinstance(message.content,str)
                        or not message.content.strip()
                    ):
                        raise ValueError("prepared message must contain a human message")
                current = deepcopy(current)
            elif name == "after_tool":
                if not isinstance(current,ToolMessage) or not isinstance(result, ToolMessage):
                    raise TypeError("after_tool must return a message list")
                if (
                    result.name,
                    result.tool_call_id,
                    result.status,
                    result.artifact
                ) != (
                    current.name,
                    current.tool_call_id,
                    current.status,
                    current.artifact
                ):
                    raise ValueError("prepared message must contain a tool message")
                current = deepcopy(current)
            elif name in ("before_tool","after_turn"):
                if not isinstance(result,Decision):
                    raise TypeError("before_tool must return a decision")
                if result.stop:
                    if not result.reason:
                        raise ValueError("before_tool must return a decision")
                    return result
            else:
                raise ValueError("unknown hook")
        if name in ("before_tool","after_turn"):
            return Decision()
        if name == "after_model":
            return None
        if isinstance(current,(list,ToolMessage)):
            return current
        raise ValueError("unknown hook")




















