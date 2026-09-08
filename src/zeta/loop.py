# ruff: noqa: F401  # Prepared imports for exercise bodies.
# pyright: reportUnusedImport=false
import asyncio
import logging

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
    status: RunStatus = "failed"
    reason = ""
    primary: BaseException | None = None
    try:
        async with asyncio.timeout(runtime.options.timeout):
            await runtime.start(prompt)
            async with runtime.io.factory() as model:
                while runtime.requests < runtime.options.max_requests:
                    await runtime.begin_turn()
                    messages = await runtime.prepare()
                    validate_history(messages)
                    runtime.requests += 1
                    try:
                        response = await runtime.io.request(
                            model, messages, max_tokens=runtime.options.output_tokens
                        )
                    except ModelHTTPError as error:
                        if (
                                runtime.requests < runtime.options.max_requests
                                and await runtime.retry(error)
                        ):
                            continue
                        raise
                    calls = response_calls(response)
                    await runtime.on_response(response)
                    results: list[ToolReturnPart] = []
                    if calls:
                        if (
                                runtime.requests >= runtime.options.max_requests
                                or runtime.tool_calls + len(calls)
                                > runtime.options.max_tool_calls
                        ):
                            raise RunLimitError("request or tool allowance exhausted")
                        runtime.tool_calls += len(calls)
                        for call in calls:
                            execution = await runtime.execute(call)
                            await runtime.on_result(execution)
                            results.append(execution.result)
                    await runtime.after_turn(results)
                    if not calls:
                        status = "completed"
                        return response.text or ""
                raise RunLimitError("request allowance exhausted")
    except BaseException as error:
        primary = error
        status = (
            "cancelled"
            if isinstance(error, asyncio.CancelledError)
            else ("stopped" if isinstance(error, RunLimitError) else "failed")
        )
        reason = (
            str(error) if isinstance(error, RunLimitError) else type(error).__name__
        )
        raise
    finally:
        try:
            await runtime.finish(status, reason)
        except BaseException as cleanup_error:
            if primary is None:
                raise
            logger.warning("cleanup failed: %s", type(cleanup_error).__name__)
