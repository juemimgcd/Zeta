# ruff: noqa: F401  # Prepared imports for exercise bodies.
# pyright: reportUnusedImport=false
import asyncio
import logging

from langchain_core.messages import ToolMessage
from openai import APIStatusError

from zeta.loop_common import RunLimitError, response_calls, validate_history
from zeta.runtime_base import RunStatus, Runtime

logger = logging.getLogger(__name__)


async def run_loop(prompt: str | None, runtime: Runtime) -> str:
    """TODO：
    1. 在总时限内启动 Runtime，维护请求与整批工具预算。
    2. 按固定顺序准备输入、请求、校验、保存、执行和配对。
    3. 调用固定接入点，不在循环里判断今天是第几天。
    4. 正常返回文本；异常/取消保存原原因，最终完成有界清理。"""
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
                    # Validate once, after all context preparation and hooks.
                    validate_history(messages)
                    runtime.requests += 1
                    try:

                        response = await runtime.io.request(
                            model,
                            messages,
                            max_tokens=runtime.options.output_tokens,
                        )
                    except APIStatusError as err:
                        if (
                                runtime.requests < runtime.options.max_requests
                                and await runtime.retry(err)
                        ):
                            continue
                        raise

                    # Validate the new response before saving or executing it.
                    calls = response_calls(response)
                    await runtime.on_response(response)
                    results: list[ToolMessage] = []
                    if calls:
                        if (
                                runtime.requests >= runtime.options.max_requests
                                or runtime.tool_calls + len(calls) > runtime.options.max_tool_calls
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
    except BaseException as err:
        primary = err
        status = (
            "cancelled"
            if isinstance(err, asyncio.CancelledError)
            else ("stopped" if isinstance(err, RunLimitError) else "failed")
        )
        reason = (
            str(err) if isinstance(err, RunLimitError) else type(err).__name__
        )
        raise

    finally:
        try:
            await runtime.finish(status, reason)
        except BaseException as cleanup_error:
            if primary is None:
                raise
            logger.warning("cleanup failed: %s", type(cleanup_error).__name__)
