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
    status:RunStatus = "failed"
    reason = ""
    primary:BaseException | None = None
    try:
        async with asyncio.timeout(runtime.options.timeout):
            async with runtime.io.factory() as model:
                await runtime.start(prompt)
                while runtime.requests < runtime.options.max_requests:
                    await runtime.begin_turn()
                    messages = await runtime.prepare()
                    validate_history(messages)
                    try:
                        response = await runtime.io.request(
                            model,
                            messages,
                            max_tokens=runtime.options.max_tokens,
                        )
                    except ModelHTTPError as e:
                        if (
                            runtime.requests < runtime.options.max_requests
                            and await runtime.retry(e)
                        ):
                            continue
                        raise

                    calls = response_calls(response)
                    results:list[ToolReturnPart] = []
                    await runtime.on_response(response)
                    if calls:
                        if (
                            runtime.requests > runtime.options.max_requests
                            or runtime.tool_calls + len(calls) > runtime.options.max_tokens
                        ):
                            raise RunLimitError("model ")

                        for call in calls:
                            execution = await runtime.execute(call)
                            await runtime.on_result(execution)
                            results.append(execution.result)
                        runtime.tool_calls += len(calls)
                    await runtime.after_turn(results)
                    if not calls:
                        status = "completed"
                        return response.text or ""
                raise RunLimitError("model ")
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






