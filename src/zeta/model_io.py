import os
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from zeta.loop_common import ModelResponseError, response_calls
from zeta.tools import TOOL_DEFINITIONS, ToolSchema


@asynccontextmanager
async def create_model() -> AsyncGenerator[ChatOpenAI]:
    with httpx.Client() as sync_client:
        async with httpx.AsyncClient() as async_client:
            yield ChatOpenAI(
                model=os.environ["LLM_MODEL"],
                base_url=os.environ["LLM_BASE_URL"],
                api_key=SecretStr(os.environ["LLM_API_KEY"]),
                use_responses_api=False,
                timeout=60.0,
                max_retries=0,
                cache=False,
                http_client=sync_client,
                http_async_client=async_client,
            )


async def request_with_tools(
        model: ChatOpenAI,
        history: Sequence[BaseMessage],
        *,
        tools: Sequence[ToolSchema] = (),
        max_tokens: int = 2048,
) -> AIMessage:
    requester = model.bind_tools(list(tools)) if tools else model  # pyright: ignore[reportUnknownMemberType]  # Upstream callback annotation contains Unknown.
    response = await requester.ainvoke(list(history), max_tokens=max_tokens)
    return response


async def request_once(
        model: ChatOpenAI,
        history: Sequence[BaseMessage],
        *,
        max_tokens: int = 2048,
) -> AIMessage:
    return await request_with_tools(
        model, history, tools=list(TOOL_DEFINITIONS.values()), max_tokens=max_tokens
    )


async def summarize_once(prompt: str) -> str:
    async with create_model() as model:
        response = await request_with_tools(model, [HumanMessage(content=prompt)])
    if response_calls(response):
        raise ModelResponseError("summary unexpectedly requested tools")
    return response.text