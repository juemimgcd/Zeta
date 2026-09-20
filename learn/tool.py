"""Tool registration, argument validation, and workspace-scoped execution."""

from collections.abc import Callable
from os import name
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import ToolCall, ToolMessage
from pydantic import BaseModel, ValidationError

from zeta.builtin_tools import ToolError
from zeta.builtin_tools.read import ReadArgs, read_file

type ToolSchema = dict[str, Any]
type ToolHandler = Callable[[Any, Path], str]
type ToolOutcome = Literal["success", "failed", "denied"]

# 工具名 →（参数模型，执行函数）；新增工具时在这里加一项。
TOOLS: dict[str, tuple[type[BaseModel], ToolHandler]] = {
    "read": (ReadArgs, read_file),
}


def tool_schema() -> list[ToolSchema]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": handler.__doc__,
                "parameters": args_model.model_json_schema()
            }

        }
        for name, (args_model, handler) in TOOLS.items()
    ]


def resolve_tool_call(call: ToolCall) -> tuple[ToolHandler, BaseModel]:
    definition = TOOLS.get(call["name"])
    if not definition:
        raise ToolError(f"Unknown tool: {call['name']}")
    args_model, handler = definition
    try:
        args = args_model.model_validate(call["args"])
    except ValidationError as e:
        raise ToolError(f"Invalid arguments: {e}")
    return handler, args


def make_tool_message(
        call: ToolCall, content: str, outcome: ToolOutcome = "success"
) -> ToolMessage:
    return ToolMessage(
        name=call["name"],
        tool_call_id=(call["id"] or ""),
        content=content,
        status="success" if outcome == "success" else "error",
        artifact=None if outcome == "success" else {"outcome": outcome},
    )


def execute_tool(call: ToolCall, workspace: Path) -> ToolMessage:
    """Execute a tool; expected failures propagate to the base Runtime."""
    handler, args = resolve_tool_call(call)
    return make_tool_message(call, handler(args, workspace))


def tool_outcome(message: ToolMessage) -> ToolOutcome:
    """Retain the original success/failed/denied event vocabulary locally."""
    if message.status == "success":
        return "success"
    return "denied" if message.artifact == {"outcome": "denied"} else "failed"