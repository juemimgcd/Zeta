# Callable 表示“可以加括号调用的对象”，常见例子是函数和方法。
# 写法 Callable[[参数类型1, 参数类型2], 返回类型]：内层列表写输入，最后写输出。
# 例如 Callable[[str], int] 接收字符串，调用后返回整数；[] 表示不接收参数。
# Awaitable[T] 表示“可以被 await 的对象”，成功等待后得到 T 类型的结果。
# 它不是结果 T 本身，也不是函数本身；协程对象、Task、Future 都属于常见可等待对象。
# async def f(...) -> str 的含义：f(...) 得到协程对象，await f(...) 才得到字符串。
import math
from collections.abc import Awaitable, Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.openai import OpenAIChatModel

from zeta.loop_common import INSTRUCTIONS
from zeta.model_io import create_model, request_once, summarize_once
from zeta.tools import execute_tool


# 模型请求函数的类型契约：规定接入的函数应接受模型、消息历史和输出上限。
# Protocol 供类型检查使用，不会替我们发请求或执行 Agent 循环。
class RequestFn(Protocol):
    # 可调用接口：model 是模型适配器，messages 是有序消息历史。
    # / 前的参数按位置传入；* 后的 max_tokens 必须按名称传入。
    # 返回 Awaitable，表示 await 后得到完整的 ModelResponse 响应对象。
    # 即 request(...) 先得到可等待对象，await request(...) 才得到模型响应。
    # 这里用普通 def 描述可调用接口的直接返回值，并没有在 Protocol 中执行网络请求。
    def __call__(
            self,
            model: OpenAIChatModel,
            messages: Sequence[ModelMessage],
            /,
            *,
            max_tokens: int,
    ) -> Awaitable[ModelResponse]: ...


# 摘要函数类型：输入一段原文，异步等待后得到摘要字符串。
# 拆开 Callable[[str], Awaitable[str]]：
# [str]：调用函数时传入一个字符串；Awaitable[str]：调用后先得到可等待对象。
# summary_fn = summarize_once 保存函数；summary_fn(prompt) 创建协程对象；
# text = await summary_fn(prompt) 执行并等待摘要，成功后 text 才是 str。
# 这与 Callable[[str], str] 不同：后者调用后直接返回字符串，不需要 await。
type SummaryFn = Callable[[str], Awaitable[str]]
# 整次 Zeta 运行的终态：完成、主动停止/额度耗尽、失败、取消。
# 这里 completed 与模型响应 state 的 complete 属于不同字段，不能混写。
type RunStatus = Literal["completed", "stopped", "failed", "cancelled"]


@dataclass(frozen=True)
# 集中保存模型通信函数；字段中保存的是函数本身，不是调用结果。
# dataclass 自动生成初始化方法；frozen 限制字段重新赋值，不递归冻结内部对象。
class ModelIO:
    # 单次请求函数：默认 request_once；模型返回工具调用后仍由 Zeta 执行。
    request: RequestFn = request_once
    # 无工具的摘要函数，供后续压缩使用；Day 1 默认循环不会自动调用它。
    summarize: SummaryFn = summarize_once
    # 模型工厂：调用 factory() 才创建模型适配对象，创建不等于完成模型生成。
    # Callable[[], OpenAIChatModel]：无需参数，调用后直接返回模型对象，因此不 await factory()。
    # 右侧 create_model 没有括号，保存的是函数；写 create_model() 才是立刻调用。
    factory: Callable[[], OpenAIChatModel] = create_model


@dataclass(frozen=True)
# 一次运行的固定配置；构造时可覆盖默认值，初始化后检查额度是否合法。
class RunOptions:
    # 最多尝试的模型请求次数；请求失败也可能已经消耗一次尝试。
    max_requests: int = 8
    # 整次运行可计入的工具调用数量；一轮可能包含多个调用。
    max_tool_calls: int = 16
    # 主运行阶段的超时秒数；异步超时不能立即打断所有同步阻塞操作。
    timeout: float = 120.0
    # 每次模型生成的输出 token 上限；不等于字数或整个运行的总用量。
    output_tokens: int = 2048

    # dataclass 完成赋值后自动调用；非法配置抛 ValueError，不返回数据。
    # 精确检查 int 可排除布尔值；isfinite 排除无穷大和 NaN。
    def __post_init__(self) -> None:
        for value in (self.max_requests, self.max_tool_calls, self.output_tokens):
            if type(value) is not int or value <= 0:
                raise ValueError("request/tool/output limits must be positive integers")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be positive and finite")


@dataclass(frozen=True)
# Zeta 自己的执行记录，将工具原始结果与最终采用结果放在一起。
# 它不是模型消息；真正回传给模型的是 result 内的 ToolReturnPart。
class ToolExecution:
    # 工具刚执行完的原始结果，用于保留处理前的内容。
    raw: ToolReturnPart
    # 最终采用并回传的结果；后续 Hook 可以在契约范围内处理它。
    result: ToolReturnPart


# 保存一次运行的状态，并实现循环各个接入位置的 Day 1 默认行为。
# 后续通过新子类增加 Hook、持久化和上下文策略，继续复用同一个 run_loop。
class Runtime:
    """Concrete Day 1 defaults. Later lessons add behavior in new subclasses."""

    # 初始化一份独立运行状态：workspace 为工作目录，io/options 可传自定义配置。
    # self 指当前实例；每个新 Runtime 都有自己的历史、执行记录和计数器。
    def __init__(
            self,
            workspace: Path,
            *,
            io: ModelIO | None = None,
            options: RunOptions | None = None,
    ) -> None:
        # 解析后的实际工作目录；strict=True 要求目录路径存在。
        self.workspace = workspace.resolve(strict=True)
        # 未指定通信函数时使用默认 ModelIO；这里只保存函数配置。
        self.io = io if io is not None else ModelIO()
        # 未指定运行限制时使用 RunOptions 的默认额度。
        self.options = options if options is not None else RunOptions()
        # 原始消息列表：元素为 ModelRequest 或 ModelResponse，保留完整 parts。
        self.history: list[ModelMessage] = []
        # 已记录的工具执行对象；与发给模型的 history 是两份不同用途的数据。
        self.executions: list[ToolExecution] = []
        # 本次运行已尝试的模型请求数，由循环在每次请求前增加。
        self.requests = 0
        # 已计入额度的工具调用数；整批预先计数，不保证全部执行成功。
        self.tool_calls = 0
        # 标记是否启动过，防止重复向同一个实例追加一份新运行的起点。
        self.started = False

    # 启动运行：要求非空 prompt，将其包装为用户消息加入 history。
    # 基础 Runtime 不支持 prompt=None；这个签名为后续恢复能力预留位置。
    async def start(self, prompt: str | None) -> None:
        if self.started:
            raise ValueError("create a fresh Runtime for each run/resume")
        if prompt is None or not prompt.strip():
            raise ValueError("nonempty prompt required")
        self.started = True
        self.history.append(
            # 类方法创建 ModelRequest，内部含 UserPromptPart；instructions 是程序指令。
            ModelRequest.user_text_prompt(prompt, instructions=INSTRUCTIONS)
        )

    # 每轮请求前的接入位置；Day 1 没有监听器，因此默认无额外动作。
    # 只有文档字符串的函数会返回 None，与未完成时抛 NotImplementedError 不同。
    async def begin_turn(self) -> None:
        """Baseline has no event subscribers."""

    # 返回历史的深复制供本轮使用；复制嵌套消息，避免直接修改原始历史。
    async def prepare(self) -> list[ModelMessage]:
        return deepcopy(self.history)

    # 保存模型的完整响应，包括文字、工具调用、结束原因等，不只保存 text。
    async def on_response(self, response: ModelResponse) -> None:
        self.history.append(response)

    # 输入 ToolCallPart 调用描述，执行本地工具，返回 ToolExecution。
    # 基础工具读取是同步操作；async 方法包裹它不会自动将其放到后台线程。
    async def execute(self, call: ToolCallPart) -> ToolExecution:
        result = execute_tool(call, self.workspace)
        # 深复制原结果作为 raw；Day 1 两份内容相同，后续结果处理可以区分它们。
        return ToolExecution(deepcopy(result), result)

    # 记录一次工具执行；此处不把结果加入 history，由 after_turn 统一补齐一批。
    async def on_result(self, execution: ToolExecution) -> None:
        self.executions.append(execution)

    # 接收本轮 ToolReturnPart 列表；有结果时统一包装为一条输入消息。
    # 结果属于 ModelRequest，因为它是程序交给模型的数据，不是模型生成的响应。
    async def after_turn(self, results: list[ToolReturnPart]) -> None:
        if results:
            self.history.append(ModelRequest(parts=results, instructions=INSTRUCTIONS))

    # 收到 ModelHTTPError 后决定是否允许重试；基础版本始终返回 False。
    # 这里只做策略判断，真正重新请求及次数控制仍由循环负责。
    async def retry(self, error: ModelHTTPError) -> bool:
        return False

    # 运行终态接入位置：status 是结果类型，reason 是原因说明。
    # Day 1 默认没有数据库持久化或监听器，调用它不会自动保存 Session。
    async def finish(self, status: RunStatus, reason: str) -> None:
        """Baseline keeps state in memory and has no persistence/subscribers."""
