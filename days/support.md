# 固定基础代码：一次准备，八天复用

不熟悉下文的类、函数和属性时，先读 [Day 1 前置知识](prerequisites.md)，再回来准备基础文件。

本路线从 Day 1 起固定入口、运行配置和接入契约。下面文件直接提供，不作为手写练习；后续单元不再给它们的另一版。已有 src 文件保留，本次文档更新不会写入或覆盖你的业务源码。

## 接入迁移范围

基准是 [GitHub 原版 9359d5f](https://github.com/juemimgcd/Zeta/tree/9359d5fadadaf82ef42ae600be22d565cf72a984/days)。保留原课程的 Runtime、异步方法、SQLite、Hooks 与并发 Worker，只替换模型框架及其消息/工具/序列化接口。Pydantic 的 BaseModel、ReadArgs 和业务数据校验仍保留。

项目已安装以下接入依赖；重新添加时可执行：

```zsh
uv add 'langchain-openai==1.6.2'
```

项目环境已安装并验证 `langchain-openai==1.6.2`、`langchain-core==1.6.2`，依赖声明与锁文件已同步更新。旧源码尚使用 PydanticAI 时不要提前移除它；完成源码迁移后再整理依赖。下面命令以你已完成对应源码练习为前提。

`ChatOpenAI` 接入提供 OpenAI Chat Completions 兼容接口的服务，模型不限定为某个厂商。通过 `.env` 配置以下三项（入口沿用 `load_dotenv()`）：

```dotenv
LLM_MODEL=你的模型名称
LLM_BASE_URL=https://你的服务地址/v1
LLM_API_KEY=你的密钥
```

模型名、地址和密钥必须属于同一服务。`LLM_BASE_URL` 填服务商提供的 API 基础地址；请求工具时，所选模型和接口还需支持 tool calling。示例固定使用 Chat Completions，不发送厂商专用的 `thinking` 参数。非 OpenAI 兼容协议需要在 `create_model` 中换用对应的 LangChain 模型集成。

`create_model` 保留可用于 `async with` 的工厂接口，但现在是我们提供的 `@asynccontextmanager`：进入后得到 ChatOpenAI，退出时关闭所持有的 HTTP 客户端。不能把原先模型对象的上下文管理能力直接假定到 LangChain 上。

`request_with_tools` 是接入层内部的单次请求助手；`request_once` 仍是原来的对外签名，带 read 定义。摘要、Manager 规划和汇总使用空工具列表。`max_retries=0` 防止库内重试绕过 Zeta 预算；`cache=False` 保持每次请求尝试的计数口径。

原 `ToolReturnPart.outcome` 在 LangChain 中拆成 `ToolMessage.status`（success/error）和本地 `artifact` 中的拒绝/失败标记。Hook 和 Session 检查 name、tool_call_id、status、artifact，仍只允许处理正文；tool_end 通过提供的 tool_outcome 恢复原 success/failed/denied 事件值。artifact 由本地保存，不作为发给模型的正文。

接口依据：[LangChain OpenAI 兼容接口 接入](https://docs.langchain.com/oss/python/integrations/chat/openai)、[消息类型](https://docs.langchain.com/oss/python/langchain/messages)、[ToolMessage](https://reference.langchain.com/python/langchain-core/messages/tool/ToolMessage)。

## 文件所有权

| 归属 | 文件 | 后续如何使用 |
| --- | --- | --- |
| 本配套文档 | app.py、runtime_base.py、model_io.py、tools.py、cli.py、storage.py | 一次准备，之后保持不变 |
| Day 1 | loop_common.py、loop.py | 唯一协议检查与唯一 run_loop，全部后续单元复用 |
| Day 2 | hooks.py、lifecycle.py、dispatch.py、hook_runtime.py | 新增 Hook/事件/调度，无需改 Day 1 |
| Day 3 | session.py、session_runtime.py | 新增提交/恢复，无需改 Day 1/2 |
| Day 4 | memory.py | 独立记忆策略 |
| Day 5 | context.py | 独立上下文选择 |
| Day 6 | compaction.py | 独立摘要策略 |
| Day 7 | integration.py | 组装前面能力，调用既有 run_loop |
| Day 8 | team_budget.py、orchestration.py | Worker 复用 Day 7，不修改父级接口 |

ReadArgs 和 read_file 保留旧版本的 Pydantic 校验与文件读取；工具说明和结果类型需按下方完整 tools.py 改为 LangChain 写法。Day 2 的异步调度放在新文件 dispatch.py，不覆盖基础工具实现。包的 __init__.py 沿用当前项目；模型接入依赖见下方迁移说明。

## 固定入口怎么扩展

`app.run_agent(prompt, workspace, *, runtime=None)` 是直接提供的稳定入口；实际循环只有 Day 1 的 `loop.run_loop`。默认 Runtime 真实执行单次模型调用和 read，并保存内存历史；不是 mock，也不把未来未实现的能力标为成功。

Runtime 的接入点从一开始就齐全：start、begin_turn、prepare、on_response、execute、on_result、after_turn、retry、finish。后续新类只增加自己的处理，并调用已有方法；它们不修改基类、不复制循环。

- Day 1：默认 Runtime，学习循环和配对。
- Day 2：传 HookRuntime，仍调用同一个 run_agent。
- Day 3：新 SessionRuntime 持久化；用同一个 run_loop 接受新输入或恢复。
- Day 7：ContextRuntime 只组装上下文和重试策略，run_session_task 是调用 run_loop 的薄入口。
- Day 8：为 Services 传共享 request/summarizer，Worker 仍调用 Day 7 入口。

`RunOptions` 的次数/时限/输出上限，`ModelIO` 的模型请求/摘要函数，`ToolExecution` 的原始与最终结果都预先定义。运行配置不随天数换签名，错误类型在 Day 1 骨架提前提供。

## 先认识基础代码中的类与函数

下面是各天共同使用的对象说明。`对象.属性` 读取该对象的数据，`对象.方法(...)` 调用行为；函数也可以作为属性保存，所以 `io.request` 是一个函数值，`await io.request(...)` 才执行并取得响应。

| 类或数据类型 | 它是什么 | 本课程使用的属性/字段 |
| --- | --- | --- |
| `BaseMessage` | LangChain 消息的公共基类，用于表示可接受不同消息子类的列表 | `content`：正文，具体格式还需按课程要求校验 |
| `SystemMessage` | 系统指令消息 | `content`：本项目固定指令 |
| `HumanMessage` | 用户级消息，也用来装低优先级参考数据 | `content`：用户输入或参考正文 |
| `AIMessage` | 一次完整模型响应 | `content`：正文；`text`：文本视图；`tool_calls`：调用字典列表；`invalid_tool_calls`：解析失败的调用；`response_metadata`：含 finish_reason 等响应信息；`usage_metadata`：用量信息或 None |
| `AIMessageChunk` | 流式响应片段 | 本课程不拿片段执行工具，由 response_calls 明确拒绝 |
| `ToolCall` | 带类型描述的字典，不是通过点号读属性的普通对象 | `name`：工具名；`args`：参数字典；`id`：本次调用编号；例如 call["args"]["path"] |
| `ToolMessage` | 交回模型的工具结果消息 | `content`：正文；`name`：工具名；`tool_call_id`：配对调用编号；`status`：success/error；`artifact`：本地附加信息，本项目用 outcome 区分 failed/denied 等结果 |
| `RequestFn` | Protocol，描述单次请求函数必须具有的调用形状 | 没有业务数据属性；`__call__` 规定接收 model/messages 和关键字 max_tokens，调用后返回可等待对象，await 后取得 AIMessage；协议自身不发送请求 |
| `ModelIO` | 集中保存三个可替换的通信函数 | `request`：单次请求函数；`summarize`：字符串输入、await 后得到字符串的摘要函数；`factory`：无参数函数，返回异步上下文管理器，供 async with 取得和释放模型资源 |
| `RunOptions` | 一次运行的限制配置 | `max_requests`：请求次数上限；`max_tool_calls`：工具调用次数上限；`timeout`：整次运行超时秒数；`output_tokens`：单次请求输出上限 |
| `ToolExecution` | 同一次工具执行的原始/最终结果对 | `raw`：Hook 处理前的 ToolMessage；`result`：交回模型的最终 ToolMessage；处理 result 不会自动清除 raw |
| `Runtime` | 循环调用的行为对象，后续通过子类增加能力 | 具体实例属性见下一张表 |
| `ToolError` | 参数、路径、读取等预期工具失败的异常 | 无新增业务属性，构造参数保存原因，由调用方转换为工具结果 |
| `ReadArgs` | read 工具的 Pydantic 参数模型 | `path`：非空路径字符串；`model_config`：严格类型、禁止额外字段的类配置；模型校验不替代实际路径检查 |
| `JsonStore` | 在 SQLite 中按类别和编号保存 JSON 字符串的存储对象 | `connection`：SQLite 连接。名字叫 JsonStore，但存储文件是 SQLite 数据库 |

`SummaryFn`、`RunStatus`、`ToolSchema` 都是类型别名：分别描述摘要函数、四种运行终态、工具定义字典；不是需要实例化的新类。`@dataclass` 为 ModelIO、RunOptions、ToolExecution 生成初始化等方法，frozen=True 禁止直接重赋字段。

| Runtime 属性 | 含义 |
| --- | --- |
| `workspace` | 解析后的实际工作目录 Path |
| `io` | ModelIO 对象，保存请求、摘要和模型工厂函数 |
| `options` | RunOptions 对象，保存运行限制 |
| `history` | 当前内存中的有序消息列表 |
| `executions` | 已记录的 ToolExecution 列表，保留 raw/result |
| `requests` | 本次已尝试的请求次数，循环更新 |
| `tool_calls` | 已计入预算的工具调用次数，循环按批次更新 |
| `started` | 是否已经启动；同一 Runtime 不重复用于另一轮运行/恢复 |

| 函数或方法 | 输入、功能和返回值 |
| --- | --- |
| `RequestFn.__call__(model, messages, /, *, max_tokens)` | 只声明请求函数契约；斜杠前参数仅限位置传入，星号后仅限关键字传入，返回 Awaitable[AIMessage] |
| `RunOptions.__post_init__()` | dataclass 初始化后自动检查正整数额度和有限正超时；成功返回 None，非法则报错 |
| `Runtime.__init__(workspace, io=..., options=...)` | 解析目录，保存依赖/配置，初始化空历史、执行记录和计数器 |
| `Runtime.start(prompt)` | 检查对象未启动且问题非空，标记 started 并加入 HumanMessage；返回 None |
| `Runtime.begin_turn()` | 每轮开始的扩展位置，基础版本不做额外动作，返回 None |
| `Runtime.prepare()` | 返回固定 SystemMessage 加 history 深拷贝组成的消息列表 |
| `Runtime.on_response(response)` | 将 AIMessage 加入内存历史，返回 None |
| `Runtime.execute(call)` | 用 asyncio.to_thread 执行同步工具函数，避免文件读取占住事件循环；返回 ToolExecution |
| `Runtime.on_result(execution)` | 将执行对象加入 executions；此时还没把本批结果全部补入 history，返回 None |
| `Runtime.after_turn(results)` | 将本轮工具结果加入 history，返回 None |
| `Runtime.retry(error)` | 返回是否允许重试；基础版本固定 False，子类可增加策略 |
| `Runtime.finish(status, reason)` | 结束扩展位置，基础版本无持久化或通知，返回 None |
| `run_agent(prompt, workspace, runtime=...)` | 使用传入 Runtime 或创建默认对象，调用同一个 run_loop，返回最终回答字符串 |
| `create_model()` | 被 asynccontextmanager 包装；配合 async with 创建并交出 ChatOpenAI，离开时关闭 HTTP 客户端；yield 交出模型，不是回答文字 |
| `request_with_tools(model, history, tools=..., max_tokens=...)` | 按需绑定工具定义并 await 一次 ainvoke，返回 AIMessage；不替 Zeta 执行工具或循环 |
| `request_once(model, history, max_tokens=...)` | 给 request_with_tools 带上本项目 read 定义，返回 AIMessage |
| `summarize_once(prompt)` | 创建模型并发送无工具请求，校验后返回摘要正文字符串 |
| `read_file(args, workspace)` | 接收已校验 ReadArgs 和目录，检查真实路径、大小等并读取 UTF-8 正文；返回字符串，预期失败抛 ToolError |
| `tools.execute_tool(call, workspace)` | 基础同步调度：校验工具名/参数，读取并把预期错误转为 ToolMessage，返回结果消息；与 Day 2 带 Hook 的异步调度函数区分 |
| `tool_outcome(message)` | 从 artifact.outcome 或消息 status 得到可显示的结果标签，返回字符串 |
| `main()` | CLI 入口，解析参数并启动异步运行，输出回答或错误；返回 None |
| `JsonStore.__init__(path)` | 创建父目录、打开连接、建立 documents 表并提交初始化 |
| `JsonStore.transaction()` | 上下文管理器，with store.transaction() 中正常结束提交，异常回滚；不返回业务结果 |
| `JsonStore.get(kind, key)` | 按类别和编号读取 JSON 字符串，不存在返回 None |
| `JsonStore.put(kind, key, body)` | 写入或覆盖 JSON 字符串，事务提交由调用方负责；返回 None |
| `JsonStore.all(kind)` | 返回某类别下按编号排序的 JSON 字符串列表 |
| `JsonStore.close()` | 关闭数据库连接，返回 None |

## 一次提供的完整文件

先将下面基础文件与 Day 1 骨架组合。app.py 导入你要完成的 loop.py，runtime_base.py 导入 Day 1 已提供定义的 loop_common.py；不存在对尚未新增的 Day 2–8 模块的导入。

## 直接提供：src/zeta/runtime_base.py

```python
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
    """Concrete Day 1 defaults. Later lessons add behavior in new subclasses."""

    def __init__(
        self,
        workspace: Path,
        *,
        io: ModelIO | None = None,
        options: RunOptions | None = None,
    ) -> None:
        self.workspace = workspace.resolve(strict=True)
        self.io = io if io is not None else ModelIO()
        self.options = options if options is not None else RunOptions()
        self.history: list[BaseMessage] = []
        self.executions: list[ToolExecution] = []
        self.requests = 0
        self.tool_calls = 0
        self.started = False

    async def start(self, prompt: str | None) -> None:
        if self.started:
            raise ValueError("create a fresh Runtime for each run/resume")
        if prompt is None or not prompt.strip():
            raise ValueError("nonempty prompt required")
        self.started = True
        self.history.append(HumanMessage(content=prompt))

    async def begin_turn(self) -> None:
        """Baseline has no event subscribers."""

    async def prepare(self) -> list[BaseMessage]:
        return [SystemMessage(content=INSTRUCTIONS), *deepcopy(self.history)]

    async def on_response(self, response: AIMessage) -> None:
        self.history.append(response)

    async def execute(self, call: ToolCall) -> ToolExecution:
        result = await asyncio.to_thread(execute_tool, call, self.workspace)
        return ToolExecution(deepcopy(result), result)

    async def on_result(self, execution: ToolExecution) -> None:
        self.executions.append(execution)

    async def after_turn(self, results: list[ToolMessage]) -> None:
        if results:
            self.history.extend(results)

    async def retry(self, error: APIStatusError) -> bool:
        return False

    async def finish(self, status: RunStatus, reason: str) -> None:
        """Baseline keeps state in memory and has no persistence/subscribers."""
```

## 直接提供：src/zeta/app.py

```python
from pathlib import Path

from zeta.loop import run_loop
from zeta.runtime_base import Runtime


async def run_agent(
    prompt: str, workspace: Path, *, runtime: Runtime | None = None
) -> str:
    """Stable, supplied entry point. The user's implementation lives in loop.py."""
    active = runtime if runtime is not None else Runtime(workspace)
    if active.workspace != workspace.resolve(strict=True):
        raise ValueError("runtime workspace mismatch")
    return await run_loop(prompt, active)
```

## 直接提供：src/zeta/model_io.py

```python
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
```

## 直接提供：src/zeta/tools.py

仅工具协议类型适配，ReadArgs 与 read_file 沿用旧版；execute_tool 仍由 Runtime 调用，不交给 LangChain 自动执行。

```python
"""A fixed, workspace-scoped read tool."""

from pathlib import Path
from typing import Any

from langchain_core.messages import ToolCall, ToolMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# 读取文件的字节上限：32768 字节，不是 32768 个汉字。
MAX_READ_BYTES = 32_768


# 预期工具错误：参数、路径或读取失败；供外层转换或显示，不表示正常结果。
class ToolError(Exception):
    """An expected tool failure safe to return to the caller."""


# read 的参数模型，继承 Pydantic BaseModel 以获得运行时数据校验能力。
class ReadArgs(BaseModel):
    """Arguments accepted by the read tool."""

    # 拒绝额外参数，启用严格类型校验；模型提供的参数仍需经过本地验证。
    model_config = ConfigDict(extra="forbid", strict=True)
    # 要读取的路径字符串，至少一个字符；路径是否存在和越界由 read_file 检查。
    path: str = Field(min_length=1, description="UTF-8 file path inside the workspace")


# 输入已校验的 ReadArgs 和工作目录 Path，成功返回 UTF-8 文件正文字符串。
# 只允许目录范围内的小型普通文件；拒绝 .git/.env 等路径，失败抛 ToolError。
def read_file(args: ReadArgs, workspace: Path) -> str:
    """Read a small UTF-8 regular file inside the workspace."""
    try:
        # 解析实际根路径，strict=True 要求它存在。
        root = workspace.resolve(strict=True)
        # Path 的 / 运算符拼接路径；resolve 解析 .. 和符号链接后再判断是否越界。
        target = (root / args.path).resolve(strict=True)
        if not root.is_dir() or not target.is_relative_to(root):
            raise ToolError("path is outside the workspace")
        # 取得相对路径；这里 relative.parts 是路径组件元组，不是模型响应 parts。
        relative = target.relative_to(root)
        if any(
            p == ".git" or p == ".env" or p.startswith(".env.") for p in relative.parts
        ):
            raise ToolError("reading this path is denied")
        if not target.is_file():
            raise ToolError("read requires a regular file")
        # Trusted local workspace; use OS isolation for hostile concurrent changes.
        # 二进制模式读取，以字节检查大小；with 结束时关闭文件。
        # 此实现假设可信本地目录，不能防住恶意并发修改路径的所有情况。
        with target.open("rb") as file:
            # 多读取一个字节，用于区分“恰好达到上限”和“超过上限”。
            data = file.read(MAX_READ_BYTES + 1)
        if len(data) > MAX_READ_BYTES:
            raise ToolError("file exceeds the 32768-byte read limit")
        # 含零字节时按非文本拒绝；随后 decode 继续检查 UTF-8 编码是否合法。
        if b"\x00" in data:
            raise ToolError("read supports UTF-8 text only")
        return data.decode("utf-8")
    # 把底层解码错误转换为可读的工具错误；from None 隐去异常链显示。
    except UnicodeError:
        raise ToolError("read supports UTF-8 text only") from None
    except OSError, ValueError, RuntimeError:
        raise ToolError("cannot read the requested workspace file") from None


# 给模型看的工具说明表，键是工具名称；它不自动调用本地 read_file。
type ToolSchema = dict[str, Any]
TOOL_DEFINITIONS: dict[str, ToolSchema] = {
    "read": {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read a UTF-8 workspace file of at most 32768 bytes.",
            "parameters": ReadArgs.model_json_schema(),
        },
    }
}


# 接收模型给出的 ToolCall，校验名称/参数并执行 read，返回 ToolMessage。
# Day 1 遇到预期失败会抛 ToolError 停止；这里尚不包装 failed 结果继续运行。
def execute_tool(call: ToolCall, workspace: Path) -> ToolMessage:
    """Dispatch the fixed read tool; the Day 1 baseline stops on expected tool failure."""
    # tool_name 是要调用哪个工具；只接受固定定义表中的名称。
    if call["name"] not in TOOL_DEFINITIONS:
        raise ToolError("unknown tool")
    try:
        # LangChain 的 ToolCall["args"] 已是字典；invalid_tool_calls 由 response_calls 拒绝。
        # 成功后得到 ReadArgs 实例，使用 args.path 读取路径字段。
        args = ReadArgs.model_validate(call["args"])
    except ValidationError:
        raise ToolError("read expects an object with a string path only") from None
    # 先执行 read_file 得到正文，再包装为工具结果对象；此处尚未发回模型。
    return ToolMessage(
        # 沿用调用中的工具名称，例如 read。
        name=call["name"],
        # 沿用这一次调用的编号，不能另造 ID；模型靠它识别结果对应哪个调用。
        tool_call_id=(call["id"] or ""),
        # content 保存实际读取正文，不是模型猜测的文件内容。
        content=read_file(args, workspace),
    )


def tool_outcome(message: ToolMessage) -> str:
    """Retain the original success/failed/denied event vocabulary locally."""
    if message.status == "success":
        return "success"
    return "denied" if message.artifact == {"outcome": "denied"} else "failed"
```

## 直接提供：src/zeta/cli.py

```python
import argparse
import asyncio
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
from openai import APIError, APIStatusError

from zeta import __version__
from zeta.app import run_agent
from zeta.loop_common import ModelResponseError, RunLimitError
from zeta.tools import ToolError


def main() -> None:
    parser = argparse.ArgumentParser(prog="zeta")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("-p", "--prompt", required=True)
    args = parser.parse_args()
    prompt = cast(str, args.prompt)
    load_dotenv(override=False)
    try:
        output = asyncio.run(run_agent(prompt, Path.cwd()))
    except ValueError:
        parser.exit(2, "zeta: invalid input, model configuration or API key\n")
    except APIStatusError as error:
        parser.exit(1, f"zeta: model request failed: HTTP {error.status_code}\n")
    except APIError:
        parser.exit(1, "zeta: model request failed\n")
    except ModelResponseError:
        parser.exit(1, "zeta: incomplete or invalid model response\n")
    except (RunLimitError, ToolError) as error:
        parser.exit(1, f"zeta: {error}\n")
    except TimeoutError:
        parser.exit(1, "zeta: run timed out\n")
    except KeyboardInterrupt:
        parser.exit(130, "zeta: cancelled\n")
    print(output)
```

## 直接提供：src/zeta/storage.py

```python
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import cast


class JsonStore:
    """Single-process teaching store; transaction ownership stays with callers."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS documents ("
            "kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, "
            "PRIMARY KEY(kind, id))"
        )
        self.connection.commit()

    @contextmanager
    def transaction(self) -> Generator[None]:
        with self.connection:
            yield

    def get(self, kind: str, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT body FROM documents WHERE kind=? AND id=?", (kind, key)
        ).fetchone()
        return None if row is None else cast(str, row[0])

    def put(self, kind: str, key: str, body: str) -> None:
        self.connection.execute(
            "INSERT INTO documents(kind,id,body) VALUES(?,?,?) "
            "ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
            (kind, key, body),
        )

    def all(self, kind: str) -> list[str]:
        rows = self.connection.execute(
            "SELECT body FROM documents WHERE kind=? ORDER BY id", (kind,)
        ).fetchall()
        return [cast(str, row[0]) for row in rows]

    def close(self) -> None:
        self.connection.close()
```

## 如何验收而不修改入口

CLI 默认演示 Day 1 的基础 Runtime；没有自动启用尚未完成的模块，也没有虚构 --resume/--stage 参数。后续用模块公开的入口或 runtime 参数运行手动任务，无需改 app.py/cli.py。

Day 2 完成后可以这样真实调用：

```zsh
uv run python -c 'import asyncio; from pathlib import Path; from dotenv import load_dotenv; from zeta.app import run_agent; from zeta.hook_runtime import HookRuntime; load_dotenv(); p=Path.cwd(); print(asyncio.run(run_agent("用 read 读取 README.md", p, runtime=HookRuntime(p))))'
```

Day 7 调用 run_session_task 前，用 create_session 创建 Session，并构造 Services；Day 8 直接调用 run_manager。调用位置可以变化，但入口实现、已经写完的函数不需要重写。

模型密钥放在本地环境或 .env；SQLite 存储目录 .zeta/ 需加入 .gitignore。真实调用与创建数据库由你完成练习后执行，文档编辑不自动运行它们。

## 完成源码练习后的检查

```zsh
uv run ruff format --check src/zeta
uv run ruff check src/zeta
uv run pyright --pythonpath .venv/bin/python
uv build
uv run zeta --help
uv run zeta --version
```

练习骨架只临时忽略预留导入未使用提示，不能把 TODO 抛出的 NotImplementedError 当作功能验收成功。静态验证与真实调用结果分别记录；不新增或修改测试、mock、fixture、snapshot、内联自测。不自动提交或推送。
