import asyncio
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path

from langchain_core.messages import ToolCall, ToolMessage

from zeta.hooks import Decision, Hooks, ToolContext
from zeta.lifecycle import Event, Listener, emit
from zeta.runtime_base import ToolExecution
from zeta.tools import ToolError, make_tool_message, resolve_tool_call


async def execute_tool(
    call: ToolCall,
    workspace: Path,
    hooks: Hooks,
    listeners: Sequence[Listener] = (),
) -> ToolExecution:
    raw: ToolMessage
    try:
        handler, args = resolve_tool_call(call)
    except ToolError as error:
        raw = make_tool_message(call, str(error), "failed")
    else:
        decision = await hooks.invoke(
            "before_tool",
            ToolContext(call["name"], (call["id"] or ""), args.model_dump(mode="json")),
        )
        if not isinstance(decision, Decision):
            raise TypeError("missing tool decision")
        if decision.stop:
            raw = make_tool_message(call, decision.reason, "denied")
        else:
            await emit(Event("tool_start", call["name"], (call["id"] or "")), listeners)
            try:
                content = await asyncio.to_thread(handler, args, workspace)
            except ToolError as error:
                raw = make_tool_message(call, str(error), "failed")
            else:
                raw = make_tool_message(call, content)
    result = await hooks.invoke("after_tool", raw)
    if not isinstance(result, ToolMessage):
        raise TypeError("missing final tool result")
    return ToolExecution(deepcopy(raw), deepcopy(result))
