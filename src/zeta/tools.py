"""A fixed, workspace-scoped read tool."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.tools import ToolDefinition

MAX_READ_BYTES = 32_768


class ToolError(Exception):
    """An expected tool failure safe to return to the caller."""


class ReadArgs(BaseModel):
    """Arguments accepted by the read tool."""

    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, description="UTF-8 file path inside the workspace")


def read_file(args: ReadArgs, workspace: Path) -> str:
    """Read a small UTF-8 regular file inside the workspace."""
    try:
        root = workspace.resolve(strict=True)
        target = (root / args.path).resolve(strict=True)
        if not root.is_dir() or not target.is_relative_to(root):
            raise ToolError("path is outside the workspace")
        relative = target.relative_to(root)
        if any(
            p == ".git" or p == ".env" or p.startswith(".env.") for p in relative.parts
        ):
            raise ToolError("reading this path is denied")
        if not target.is_file():
            raise ToolError("read requires a regular file")
        # Trusted local workspace; use OS isolation for hostile concurrent changes.
        with target.open("rb") as file:
            data = file.read(MAX_READ_BYTES + 1)
        if len(data) > MAX_READ_BYTES:
            raise ToolError("file exceeds the 32768-byte read limit")
        if b"\x00" in data:
            raise ToolError("read supports UTF-8 text only")
        return data.decode("utf-8")
    except UnicodeError:
        raise ToolError("read supports UTF-8 text only") from None
    except OSError, ValueError, RuntimeError:
        raise ToolError("cannot read the requested workspace file") from None


TOOL_DEFINITIONS = {
    "read": ToolDefinition(
        name="read",
        description="Read a UTF-8 workspace file of at most 32768 bytes.",
        parameters_json_schema=ReadArgs.model_json_schema(),
        strict=False,
    )
}


def execute_tool(call: ToolCallPart, workspace: Path) -> ToolReturnPart:
    """Dispatch the fixed read tool; the Day 1 baseline stops on expected tool failure."""
    if call.tool_name not in TOOL_DEFINITIONS:
        raise ToolError("unknown tool")
    try:
        args = (
            ReadArgs.model_validate_json(call.args)
            if isinstance(call.args, str)
            else ReadArgs.model_validate(call.args)
        )
    except ValidationError:
        raise ToolError("read expects an object with a string path only") from None
    return ToolReturnPart(
        tool_name=call.tool_name,
        tool_call_id=call.tool_call_id,
        content=read_file(args, workspace),
    )
