# 固定基础代码：一次准备，九天复用

不熟悉下文的类、函数和属性时，先读 [Day 1 前置知识](prerequisites.md)，再回来准备基础文件。

本路线从 Day 1 起固定入口、运行配置和接入契约。下面文件直接提供，不作为手写练习；后续单元不再给它们的另一版。已有 src 文件保留，本次文档更新不会写入或覆盖你的业务源码。

## 接入迁移范围

基准是 [GitHub 原版 9359d5f](https://github.com/juemimgcd/Zeta/tree/9359d5fadadaf82ef42ae600be22d565cf72a984/days)。保留原课程的 Runtime、异步方法、SQLite、Hooks 与并发 Worker；模型接入使用 LangChain，并同步当前工具注册和单次请求接口。Pydantic 的 BaseModel、ReadArgs 和业务数据校验仍保留。

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

`request_once` 直接完成一次请求，默认携带已注册工具定义（`tools=None`）；显式传入 `tools=()` 或 `tools=[]` 时不携带工具，也可以传入指定工具列表。摘要、Manager 规划和汇总显式使用空工具列表。`max_retries=0` 防止库内重试绕过 Zeta 预算；`cache=False` 保持每次请求尝试的计数口径。

原 `ToolReturnPart.outcome` 在 LangChain 中拆成 `ToolMessage.status`（success/error）和本地 `artifact` 中的拒绝/失败标记。Hook 和 Session 检查 name、tool_call_id、status、artifact，仍只允许处理正文；tool_end 通过提供的 tool_outcome 恢复原 success/failed/denied 事件值。artifact 由本地保存，不作为发给模型的正文。

接口依据：[LangChain OpenAI 兼容接口 接入](https://docs.langchain.com/oss/python/integrations/chat/openai)、[消息类型](https://docs.langchain.com/oss/python/langchain/messages)、[ToolMessage](https://reference.langchain.com/python/langchain-core/messages/tool/ToolMessage)。

## 文件所有权

| 归属 | 文件 | 后续如何使用 |
| --- | --- | --- |
| 本配套文档 | app.py、runtime_base.py、model_io.py、tools.py、builtin_tools/read.py、builtin_tools/__init__.py、__init__.py、cli.py、storage.py | 基础代码统一准备，后续单元直接复用 |
| Day 1 | loop_common.py、loop.py | 唯一协议检查与唯一 run_loop，全部后续单元复用 |
| Day 2 | hooks.py、lifecycle.py、dispatch.py、hook_runtime.py | 新增 Hook/事件/调度，无需改 Day 1 |
| Day 3 | session.py、session_runtime.py | 新增提交/恢复，无需改 Day 1/2 |
| Day 4 | memory.py | 独立记忆策略 |
| Day 5 | context.py | 独立上下文选择 |
| Day 6 | compaction.py | 独立摘要策略 |
| Day 7 | integration.py | 组装前面能力，调用既有 run_loop |
| Day 8 | celery_app.py、queue_tools.py、queue_runtime.py | 为 Day 2 的 dispatch.py 增加可选 runner，复用 Hooks 和 Session |
| Day 9 | team_budget.py、orchestration.py | Worker 复用 Day 7，不修改父级接口 |

`ReadArgs` 和普通函数 `read_file` 位于 `builtin_tools/read.py`；`tools.py` 直接导入它们，在 `TOOLS` 中保存工具名与（参数模型，执行函数）的对应关系，并提供参数解析和结果包装。`ToolError` 定义在 `builtin_tools/__init__.py`，避免具体工具反向依赖调度模块。包的 `__init__.py` 只负责版本信息。Day 2 的 `dispatch.py` 复用这些公共函数。

## 固定入口怎么扩展

`app.run_agent(prompt, workspace, *, runtime=None)` 是直接提供的稳定入口；实际循环只有 Day 1 的 `loop.run_loop`。默认 Runtime 真实执行单次模型调用和 read，并保存内存历史；不是 mock，也不把未来未实现的能力标为成功。

Runtime 的接入点从一开始就齐全：start、begin_turn、prepare、on_response、execute、on_result、after_turn、retry、finish。后续新类只增加自己的处理，并调用已有方法；它们不修改基类、不复制循环。

- Day 1：默认 Runtime，学习循环和配对。
- Day 2：传 HookRuntime，仍调用同一个 run_agent。
- Day 3：新 SessionRuntime 持久化；用同一个 run_loop 接受新输入或恢复。
- Day 7：ContextRuntime 只组装上下文和重试策略，run_session_task 是调用 run_loop 的薄入口。
- Day 8：QueueRuntime 继承 ContextRuntime，通过可选 runner 将 read 交给 Celery Worker。
- Day 9：为 Services 传共享 request/summarizer，Worker 仍调用 Day 7 入口。

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
| `ToolError` | 参数、路径、读取等预期工具失败的异常 | 构造参数保存原因；基础 Runtime 向外抛出，Day 2 调度器转换为失败结果 |
| `ReadArgs` | read 工具的 Pydantic 参数模型 | `path`：非空路径字符串；`model_config`：严格类型、禁止额外字段的类配置；模型校验不替代实际路径检查 |
| `JsonStore` | 在 SQLite 中按类别和编号保存 JSON 字符串的存储对象 | `connection`：SQLite 连接。名字叫 JsonStore，但存储文件是 SQLite 数据库 |

`SummaryFn`、`RunStatus`、`ToolSchema`、`ToolHandler`、`ToolOutcome` 都是类型别名，分别描述摘要函数、运行终态、给模型的工具 schema 字典、工具执行函数和 success/failed/denied 结果标签。`TOOLS` 是普通字典，每项保存参数模型和执行函数；`ToolSchema` 是发给模型的说明，不包含执行函数。`@dataclass` 为 ModelIO、RunOptions、ToolExecution 生成初始化等方法，frozen=True 禁止直接重赋字段。

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
| `request_once(model, history, tools=None, max_tokens=...)` | 默认绑定已注册工具定义，传空序列则禁用工具；await 一次 ainvoke，返回完整 AIMessage，不执行工具或循环 |
| `summarize_once(prompt)` | 创建模型并发送无工具请求，校验后返回摘要正文字符串 |
| `tool_schemas()` | 从注册表生成给模型的工具 schema 列表，不包含本地 handler |
| `resolve_tool_call(call)` | 按名称从 TOOLS 取出 args_model 和 handler，用参数模型校验，返回 handler 和参数实例；未知工具或参数无效抛 ToolError |
| `make_tool_message(call, content, outcome="success")` | 保留调用名称和 ID，统一构造成功、失败或拒绝的 ToolMessage；不负责捕获异常 |
| `read_file(args, workspace)` | 接收已校验 ReadArgs 和目录，检查真实路径、大小等并读取 UTF-8 正文；返回字符串，预期失败抛 ToolError |
| `tools.execute_tool(call, workspace)` | 基础同步调度：resolve_tool_call → handler → make_tool_message；成功返回 ToolMessage，ToolError 向外抛出；Day 2 的异步调度才把预期工具错误包装为失败结果 |
| `tool_outcome(message)` | 从 artifact.outcome 或消息 status 得到可显示的结果标签，返回字符串 |
| `main()` | CLI 入口，解析参数并启动异步运行，输出回答或错误；返回 None |
| `JsonStore.__init__(path)` | 创建父目录、打开连接、建立 documents 表并提交初始化 |
| `JsonStore.transaction()` | 上下文管理器，with store.transaction() 中正常结束提交，异常回滚；不返回业务结果 |
| `JsonStore.get(kind, key)` | 按类别和编号读取 JSON 字符串，不存在返回 None |
| `JsonStore.put(kind, key, body)` | 写入或覆盖 JSON 字符串，事务提交由调用方负责；返回 None |
| `JsonStore.all(kind)` | 返回某类别下按编号排序的 JSON 字符串列表 |
| `JsonStore.close()` | 关闭数据库连接，返回 None |

## 模型请求中的工具参数

| 调用方式 | 发给模型的工具说明 |
| --- | --- |
| `request_once(model, history)` 或 `tools=None` | 当前注册表的全部工具，目前内置 read |
| `request_once(model, history, tools=())` 或 `tools=[]` | 不携带工具；摘要、Manager 规划和汇总采用这种方式 |
| `request_once(model, history, tools=selected_tools)` | 只使用传入列表，不额外合并注册表 |

`ModelIO.request` 只是保存函数；默认指向 `request_once`，不增加一次模型请求。`request_once` 中一次 `ainvoke` 返回完整 `AIMessage`，由 Loop 检查和处理。`summarize_once` 不经过 Loop，所以自己调用 `response_calls` 检查响应，再拒绝意外工具调用并返回文本。

`RequestFn` 只规定 Loop 需要的 model、messages、max_tokens，不要求所有替代函数都暴露 tools 参数。Day 9 的 `SharedBudget.request_read` 仍满足这个接口；它通过预算入口把工具列表交给 `request_once`。

## 一次提供的完整文件

先将下面基础文件与 Day 1 骨架组合。app.py 导入你要完成的 loop.py，runtime_base.py 导入 Day 1 已提供定义的 loop_common.py；不存在对尚未新增的 Day 2–9 模块的导入。

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
from zeta.tools import ToolSchema, tool_schemas


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


async def request_once(
    model: ChatOpenAI,
    history: Sequence[BaseMessage],
    *,
    tools: Sequence[ToolSchema] | None = None,
    max_tokens: int = 2048,
) -> AIMessage:
    """Request once; None uses registered tools, an empty sequence disables them."""
    schemas = tool_schemas() if tools is None else list(tools)
    requester = model.bind_tools(schemas) if schemas else model  # pyright: ignore[reportUnknownMemberType]  # Upstream callback annotation contains Unknown.
    return await requester.ainvoke(list(history), max_tokens=max_tokens)


async def summarize_once(prompt: str) -> str:
    async with create_model() as model:
        response = await request_once(model, [HumanMessage(content=prompt)], tools=())
    if response_calls(response):
        raise ModelResponseError("summary unexpectedly requested tools")
    return response.text
```

## 直接提供：src/zeta/tools.py

工具名到参数模型、函数的对应表与参数校验集中在 tools.py，具体读取逻辑放在 builtin_tools/read.py；execute_tool 仍由 Runtime 调用，不交给 LangChain 自动执行。

```python
"""Tool registration, argument validation, and workspace-scoped execution."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import ToolCall, ToolMessage
from pydantic import BaseModel, ValidationError

from zeta.builtin_tools import ToolError
from zeta.builtin_tools.read import ReadArgs, read_file

type ToolSchema = dict[str, Any]
type ToolHandler = Callable[[Any, Path], str]
type ToolOutcome = Literal["success", "failed", "denied"]


# 工具名 →（参数模型，执行函数）；新增工具时在这里加一项。
TOOLS: dict[str, tuple[type[BaseModel], ToolHandler]] = {
    "read": (ReadArgs, read_file),
}


def tool_schemas() -> list[ToolSchema]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": handler.__doc__ or name,
                "parameters": args_model.model_json_schema(),
            },
        }
        for name, (args_model, handler) in TOOLS.items()
    ]


def resolve_tool_call(call: ToolCall) -> tuple[ToolHandler, BaseModel]:
    """Find the tool and validate model-supplied arguments once."""
    definition = TOOLS.get(call["name"])
    if definition is None:
        raise ToolError(f"unknown tool: {call['name']}")
    args_model, handler = definition
    try:
        args = args_model.model_validate(call["args"])
    except ValidationError:
        raise ToolError(f"invalid arguments for tool: {call['name']}") from None
    return handler, args


def make_tool_message(
    call: ToolCall, content: str, outcome: ToolOutcome = "success"
) -> ToolMessage:
    return ToolMessage(
        name=call["name"],
        tool_call_id=(call["id"] or ""),
        content=content,
        status="success" if outcome == "success" else "error",
        artifact=None if outcome == "success" else {"outcome": outcome},
    )


def execute_tool(call: ToolCall, workspace: Path) -> ToolMessage:
    """Execute a tool; expected failures propagate to the base Runtime."""
    handler, args = resolve_tool_call(call)
    return make_tool_message(call, handler(args, workspace))


def tool_outcome(message: ToolMessage) -> ToolOutcome:
    """Retain the original success/failed/denied event vocabulary locally."""
    if message.status == "success":
        return "success"
    return "denied" if message.artifact == {"outcome": "denied"} else "failed"
```

具体读取工具移到 `src/zeta/builtin_tools/read.py`：

```python
"""Read tool: metadata, arguments, and file-reading implementation."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from zeta.builtin_tools import ToolError

MAX_READ_BYTES = 32_768


class ReadArgs(BaseModel):
    """Arguments accepted by the read tool."""

    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, description="UTF-8 file path inside the workspace")


def read_file(args: ReadArgs, workspace: Path) -> str:
    """Read a UTF-8 workspace file of at most 32768 bytes."""
    try:
        root = workspace.resolve(strict=True)
        # 解析 .. 和符号链接后再检查工作区边界。
        target = (root / args.path).resolve(strict=True)
        if not root.is_dir() or not target.is_relative_to(root):
            raise ToolError("path is outside the workspace")
        relative = target.relative_to(root)
        if any(
            p == ".git" or p == ".env" or p.startswith(".env.") for p in relative.parts
        ):
            raise ToolError("reading this path is denied")
        if not target.is_file():
            raise ToolError("read requires a regular file")
        # 假设可信本地目录；恶意并发修改路径需要 OS 隔离。
        with target.open("rb") as file:
            # 多读一个字节以判断是否超限。
            data = file.read(MAX_READ_BYTES + 1)
        if len(data) > MAX_READ_BYTES:
            raise ToolError("file exceeds the 32768-byte read limit")
        if b"\x00" in data:
            raise ToolError("read supports UTF-8 text only")
        return data.decode("utf-8")
    except UnicodeError:
        raise ToolError("read supports UTF-8 text only") from None
    except OSError, ValueError, RuntimeError:
        raise ToolError("cannot read the requested workspace file") from None
```

读取实现先用 `resolve(strict=True)` 解析实际路径，再判断工作区范围；`relative.parts` 是路径组件元组，用于检查受限目录和文件名。二进制读取的上限按字节计算，多读一个字节用于判断超限；`with` 自动关闭文件，`decode("utf-8")` 校验编码。预期的读取与解码错误转换为 `ToolError`。

`src/zeta/builtin_tools/__init__.py` 只提供工具共用的错误类型，不导入或自动注册具体工具：

```python
"""Shared error type for built-in tools."""


class ToolError(Exception):
    """An expected tool failure safe to return to the caller."""
```

`src/zeta/__init__.py` 保留版本信息。工具表由 `tools.py` 显式定义，无需在包初始化时触发注册：

```python
"""Zeta package."""

from importlib.metadata import version

# 从已安装的 zeta 包元数据读取版本字符串，用于 CLI --version。
__version__ = version("zeta")
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

Day 7 调用 run_session_task 前，用 create_session 创建 Session，并构造 Services；Day 9 直接调用 run_manager。调用位置可以变化，但入口实现、已经写完的函数不需要重写。

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
