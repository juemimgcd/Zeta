import asyncio
import logging

from langchain_core.messages import ToolMessage
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ToolReturnPart

from zeta.loop_common import RunLimitError, response_calls, validate_history
from zeta.runtime_base import RunStatus, Runtime

# 当前模块的日志记录器；日志用于诊断，不是模型回复内容。
logger = logging.getLogger(__name__)


# 唯一循环的练习入口：prompt 为用户输入，runtime 保存状态并提供各步骤。
# 目标是异步返回最终文字；当前文件尚未完成，以下注释不表示已能运行。
async def run_loop(prompt: str | None, runtime: Runtime) -> str:
    """Written once on Day 1; reused unchanged by every later lesson."""
    status:RunStatus = "failed"
    reason = ""
    primary:BaseException | None = None
    try:
        async with asyncio.timeout(runtime.options.timeout):
            await runtime.start(prompt)
            async with runtime.io.factory() as model:
                await runtime.begin_turn()
                while runtime.requests < runtime.options.max_requests:
                    messages = await runtime.prepare()
                    validate_history(messages)
                    try:
                        response = await runtime.io.request(
                            model,
                            messages,
                            max_tokens=runtime.options.output_tokens
                        )
                    except ModelHTTPError as e:
                        if (
                            runtime.requests < runtime.options.max_requests
                            or await runtime.retry(e)
                        ):
                            continue
                    calls = response_calls(response)
                    await runtime.on_response(response)
                    results:list[ToolMessage] = []
                    if calls:
                        if (
                            runtime.requests >= runtime.options.max_requests
                            or runtime.tool_calls + len(calls) >= runtime.options.max_tool_calls
                        ):
                            raise RunLimitError("")
                        runtime.tool_calls += len(calls)
                        for call in calls:
                            execution = await runtime.execute(call)
                            await runtime.on_result(execution)
                            results.append(execution.result)
                    if not calls:
                        status = "completed"
                        return response.text or ""


                raise RunLimitError("")

    except BaseException as e:
        primary = e
        status = (
            "stopped"
            if isinstance(e,asyncio.CancelledError)
            else ("canceled" if isinstance(e,RuntimeError) else "failed")
        )
        reason = str(e) if isinstance(e,RuntimeError) else type(e).__name__
        raise
    finally:
        try:
            await runtime.finish(status,reason)
        except BaseException as e:
            if primary is None:
                raise
            logger.error("")

























