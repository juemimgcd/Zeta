from collections.abc import AsyncGenerator

from pydantic_ai.direct import model_request, model_request_stream
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelRequest,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
)

from zeta.model_io import create_model

INSTRUCTIONS = "You are Zeta, a concise local coding agent."


async def run_prompt(prompt: str) -> str:
    """Request one complete text response; do not run an Agent loop."""
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    request = ModelRequest.user_text_prompt(prompt, instructions=INSTRUCTIONS)
    async with create_model() as model:
        response = await model_request(
            model, [request], model_settings={"timeout": 60.0}
        )
    text = response.text
    if (
        response.state != "complete"
        or response.finish_reason != "stop"
        or any(isinstance(part, ToolCallPart) for part in response.parts)
        or text is None
        or not text.strip()
    ):
        raise UnexpectedModelBehavior("incomplete or empty text response")
    return text


async def stream_prompt(prompt: str) -> AsyncGenerator[str]:
    """Yield text only; let PydanticAI assemble the complete response."""
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    request = ModelRequest.user_text_prompt(prompt, instructions=INSTRUCTIONS)
    async with (
        create_model() as model,
        model_request_stream(
            model, [request], model_settings={"timeout": 60.0}
        ) as stream,
    ):
        async for event in stream:
            if (
                isinstance(event, PartStartEvent)
                and isinstance(event.part, TextPart)
                and event.part.content
            ):
                yield event.part.content
            elif (
                isinstance(event, PartDeltaEvent)
                and isinstance(event.delta, TextPartDelta)
                and event.delta.content_delta
            ):
                yield event.delta.content_delta
        response = stream.get()
    text = response.text
    if (
        response.state != "complete"
        or response.finish_reason != "stop"
        or any(isinstance(part, ToolCallPart) for part in response.parts)
        or text is None
        or not text.strip()
    ):
        raise UnexpectedModelBehavior("incomplete or empty text response")
