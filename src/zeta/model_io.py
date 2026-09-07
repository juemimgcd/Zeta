from collections.abc import Sequence

from pydantic_ai.direct import model_request
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel

from zeta.tools import TOOL_DEFINITIONS


def create_model() -> OpenAIChatModel:
    return OpenAIChatModel("deepseek-chat", provider="deepseek")


async def request_once(
    model: OpenAIChatModel, history: Sequence[ModelMessage]
) -> ModelResponse:
    return await model_request(
        model,
        history,
        model_settings={"timeout": 60.0},
        model_request_parameters=ModelRequestParameters(
            function_tools=list(TOOL_DEFINITIONS.values())
        ),
    )
