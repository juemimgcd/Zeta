import asyncio
import math
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from openai import APIStatusError

from zeta.loop_common import INSTRUCTIONS
from zeta.model_io import create_model, request_once, summarize_once
from zeta.tools import execute_tool


class RequestFn(Protocol):
    def __call__(
            self,
            model: ChatOpenAI,
            messages: Sequence[BaseMessage],
            /,
            *,
            max_tokens: int,
    ) -> Awaitable[AIMessage]: ...


type SummaryFn = Callable[[str], Awaitable[str]]
type RunStatus = Literal["completed", "stopped", "failed", "cancelled"]


@dataclass(frozen=True)
class ModelIO:
    request: RequestFn = request_once
    summarize: SummaryFn = summarize_once
    factory: Callable[[], AbstractAsyncContextManager[ChatOpenAI]] = create_model


@dataclass(frozen=True)
class RunOptions:
    max_requests: int = 8
    max_tool_calls: int = 16
    timeout: float = 120.0
    output_tokens: int = 2048

    def __post_init__(self) -> None:
        for value in (self.max_requests, self.max_tool_calls, self.output_tokens):
            if type(value) is not int or value <= 0:
                raise ValueError("request/tool/output limits must be positive integers")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be positive and finite")


@dataclass(frozen=True)
class ToolExecution:
    raw: ToolMessage
    result: ToolMessage


class Runtime:
    def __init__(
            self,
            workspace: Path,
            *,
            io:ModelIO | None = None,
            options: RunOptions | None = None,
    ) -> None:
        self.workspace = workspace.resolve(strict=True)
        self.io = io if io is not None else ModelIO()
        self.options = options if options is not None else RunOptions()
        self.history:list[BaseMessage] = []
        self.executions:list[ToolExecution] = []
        self.requests = 0
        self.tool_calls = 0
        self.start = False


    async def start(self,prompt:str | None = None) -> None:
        if self.start:
            raise ValueError()
        if prompt is None or not prompt.strip():
            raise ValueError("prompt must not be empty")
        self.start = True
        self.history.append(HumanMessage(content=prompt))

    async def begin_turn(self) -> None:
        pass

    async def prepare(self) -> list[BaseMessage]:
        return [SystemMessage(content=INSTRUCTIONS),*deepcopy(self.history)]

    async def on_response(self,response:AIMessage) -> None:
        self.history.append(response)

    async def execute(self,call:ToolCall) -> ToolExecution:
        result = await asyncio.to_thread(execute_tool,call,self.workspace)
        return ToolExecution(
            deepcopy(result),
            result
        )

    async def on_result(self,execution:ToolExecution) -> None:
        self.executions.append(execution)

    async def after_turn(self,results:list[ToolMessage]) -> None:
        if results:
            self.history.extend(results)

    async def retry(self,error:APIStatusError) -> bool:
        return False

    async def finish(self,status:RunStatus,reason:str) -> None:
        pass

















