# ruff: noqa: F401  # Prepared imports for exercise bodies.
# pyright: reportUnusedImport=false
import asyncio
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path

from langchain_core.messages import ToolCall, ToolMessage
from pydantic import ValidationError

from zeta.hooks import Decision, Hooks, ToolContext
from zeta.lifecycle import Event, Listener, emit
from zeta.runtime_base import ToolExecution
from zeta.tools import ReadArgs, ToolError, read_file


async def execute_tool(
        call: ToolCall,
        workspace: Path,
        hooks: Hooks,
        listeners: Sequence[Listener] = (),
) -> ToolExecution:
    raw: ToolMessage | None = None
    args: ReadArgs | None = None
    try:
        if call["name"] != "read":
            raise ToolError("")
        args = ReadArgs.model_validate(call["args"])
    except ToolError, ValueError:
        raw = ToolMessage(
            name=call["name"],
            tool_call_id=(call["id"] or ""),
            content="unknown tool or invalid read arguments",
            status="error",
            artifact={"outcome": "failed"},
        )
    if args is not None:
        decision = await hooks.invoke(
            "before_tool", ToolContext(call["name"], (call["id"] or ""), args.path)
        )
        if not isinstance(decision, Decision):
            raise TypeError("missing tool decision")
        if decision.stop:
            raw = ToolMessage(
                name=call["name"],
                tool_call_id=(call["id"] or ""),
                content=decision.reason,
                status="error",
                artifact={"outcome": "denied"},
            )
        else:
            await emit(Event("tool_start", call["name"], (call["id"] or "")), listeners)
            try:
                content = await asyncio.to_thread(read_file, args, workspace)
            except ToolError as error:
                raw = ToolMessage(
                    name=call["name"],
                    tool_call_id=(call["id"] or ""),
                    content=str(error),
                    status="error",
                    artifact={"outcome": "failed"},
                )
            else:
                raw = ToolMessage(
                    name=call["name"],
                    tool_call_id=(call["id"] or ""),
                    content=content,
                )
    if raw is None:
        raise RuntimeError("missing raw tool result")
    result = await hooks.invoke("after_tool", raw)
    if not isinstance(result, ToolMessage):
        raise TypeError("missing final tool result")
    return ToolExecution(deepcopy(raw), deepcopy(result))
