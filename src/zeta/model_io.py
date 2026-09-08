from collections.abc import Sequence

from pydantic_ai.direct import model_request
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel

from zeta.tools import TOOL_DEFINITIONS


# 创建 DeepSeek 模型适配器，不执行完整 Agent 任务。
# OpenAIChatModel 指兼容的通信格式；provider="deepseek" 才指定这里的服务商。
def create_model() -> OpenAIChatModel:
    return OpenAIChatModel("deepseek-chat", provider="deepseek")


# 发送一次模型请求：model 为适配器，history 为完整消息序列。
# max_tokens 控制本次输出长度；await 后返回 ModelResponse，保留全部 parts。
# 此函数不会执行响应中的工具调用，也不会自动继续下一轮。
async def request_once(
        model: OpenAIChatModel,
        history: Sequence[ModelMessage],
        *,
        max_tokens: int = 2048,
) -> ModelResponse:
    # 调用 PydanticAI direct API，交给库完成一次通信和服务商格式适配。
    return await model_request(
        model,
        history,
        # 本次请求的超时与输出额度；与外层整次运行的额度是不同层次。
        model_settings={"timeout": 60.0, "max_tokens": max_tokens},
        model_request_parameters=ModelRequestParameters(
            # 给模型看的工具定义列表；描述工具及参数格式，不传入本地函数执行结果。
            function_tools=list(TOOL_DEFINITIONS.values())
        ),
    )


# 将 prompt 当作待摘要输入，执行一次无工具请求并返回非空摘要文字。
# 响应不完整或非正常结束时抛 ValueError；此函数本身不管理历史压缩范围。
async def summarize_once(prompt: str) -> str:
    # 进入模型的异步资源上下文，退出时按适配器约定管理客户端资源。
    async with create_model() as model:
        response = await model_request(
            model,
            # 把字符串包装为一条用户输入消息；这里没有沿用完整会话历史。
            [ModelRequest.user_text_prompt(prompt)],
            model_settings={"timeout": 60.0, "max_tokens": 2048},
            # 空工具列表：摘要请求没有被授予 read 等函数工具。
            model_request_parameters=ModelRequestParameters(function_tools=[]),
        )
    # state="complete" 表示响应完整，finish_reason="stop" 表示正常结束。
    # text 可能是 None；先用空字符串兜底，再 strip 检查是否只有空白。
    if (
            response.state != "complete"
            or response.finish_reason != "stop"
            or not (response.text or "").strip()
    ):
        raise ValueError("incomplete summary response")
    return response.text or ""