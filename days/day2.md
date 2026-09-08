# Day 2：新增 Hooks、事件与工具调度

[总览](summary.md) · [固定基础代码](support.md)

## 核心问题

在已经完成的循环中加入权限检查、结果处理和事件，怎样不改循环源码？今天新增 Hooks 与调度实现，配套 HookRuntime 负责连接 Day 1 已经预留好的调用位置。

## 今天新增什么，哪些文件不动

**今天只新增：** `hooks.py`、`lifecycle.py`、`dispatch.py`、`hook_runtime.py`。每个文件的实现只在它所属的这一天给出。

**保留不动：** support.md 的固定基础文件及前面各天已完成的全部文件。今天不替换 app.py，不重新填写 run_agent/run_loop，不复制一份旧循环改名。

## 本日实现与边界

- hooks.py：按注册顺序 await，快照隔离，按五类 Hook 分别检查返回契约。
- lifecycle.py：观察性通知与控制决策分开；普通监听器错误不触发工具重放，取消传播。
- dispatch.py：预期工具错误转 failed，拒绝转 denied，Hook 错误不包装成工具失败；保留 raw 与最终结果。
- hook_runtime.py 是直接提供的接线代码，调用已有 Runtime 方法后加入 Hook/事件。新类扩展行为，不修改或重复实现 Runtime/run_loop。
- 五个 Hook 分别为 before_model、after_model、before_tool、after_tool、after_turn；before_model 仅能添加低优先级数据，after_model 只读，after_tool 不可改 ID/名称/状态。

## 完整练习骨架

导包、异常类、字段、初始化和辅助实现已给出，只填 TODO 函数体。NotImplementedError 是未完成提示；移除它并填写真实逻辑后再验收。骨架暂时关闭未使用导入提示，其他类型检查保持开启。

### src/zeta/hooks.py

只填写：`Hooks.invoke`、`Hooks.register`。

```python
# ruff: noqa: F401  # Prepared imports for exercise bodies.
# pyright: reportUnusedImport=false
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolReturnPart,
    UserPromptPart,
)

from zeta.loop_common import validate_history

type HookName = Literal[
    "before_model", "after_model", "before_tool", "after_tool", "after_turn"
]


@dataclass(frozen=True)
class Decision:
    stop: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ToolContext:
    name: str
    call_id: str
    path: str


type HookContext = list[ModelMessage] | ModelResponse | ToolContext | ToolReturnPart
type HookResult = list[ModelMessage] | ToolReturnPart | Decision | None
type Callback = Callable[[HookContext], Awaitable[HookResult]]


class Hooks:
    def __init__(self) -> None:
        self.callbacks: dict[HookName, list[Callback]] = {
            name: []
            for name in (
                "before_model",
                "after_model",
                "before_tool",
                "after_tool",
                "after_turn",
            )
        }

    def register(self, name: HookName, callback: Callback) -> None:
        """TODO：拒绝未知名称，将回调追加到对应列表。"""
        raise NotImplementedError("请完成 Hooks.register")

    async def invoke(self, name: HookName, context: HookContext) -> HookResult:
        """TODO：
        1. 每次给回调深拷贝快照，逐个 await。
        2. 按 Hook 类型验证返回值及修改边界。
        3. 变换类串联新视图，决策类遇到 stop/deny 提前返回。
        4. 不吞掉 Hook 异常和取消。"""
        raise NotImplementedError("请完成 Hooks.invoke")
```

### src/zeta/lifecycle.py

只填写：`emit`、`finish_event`。

```python
# ruff: noqa: F401  # Prepared imports for exercise bodies.
# pyright: reportUnusedImport=false
import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    kind: str
    detail: str = ""
    call_id: str = ""


type Listener = Callable[[Event], Awaitable[None]]


async def emit(event: Event, listeners: Sequence[Listener]) -> None:
    """TODO：按本日契约实现 emit，写完与下方同名函数逐分支核对。"""
    raise NotImplementedError("请完成 emit")


async def finish_event(status: str, listeners: Sequence[Listener]) -> None:
    """TODO：按本日契约实现 finish_event，写完与下方同名函数逐分支核对。"""
    raise NotImplementedError("请完成 finish_event")
```

### src/zeta/dispatch.py

只填写：`execute_tool`。

```python
# ruff: noqa: F401  # Prepared imports for exercise bodies.
# pyright: reportUnusedImport=false
import asyncio
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

from zeta.hooks import Decision, Hooks, ToolContext
from zeta.lifecycle import Event, Listener, emit
from zeta.runtime_base import ToolExecution
from zeta.tools import ReadArgs, ToolError, read_file


async def execute_tool(
    call: ToolCallPart,
    workspace: Path,
    hooks: Hooks,
    listeners: Sequence[Listener] = (),
) -> ToolExecution:
    """TODO：按本日契约实现 execute_tool，写完与下方同名函数逐分支核对。"""
    raise NotImplementedError("请完成 execute_tool")
```

### src/zeta/hook_runtime.py

直接提供的接入代码，原样使用；内部调用前面已完成的方法，不重新实现它们。

```python
from collections.abc import Sequence
from pathlib import Path

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

from zeta.dispatch import execute_tool
from zeta.hooks import Decision, Hooks
from zeta.lifecycle import Event, Listener, emit, finish_event
from zeta.loop_common import RunStopped
from zeta.runtime_base import ModelIO, RunOptions, RunStatus, Runtime, ToolExecution


class HookRuntime(Runtime):
    def __init__(
        self,
        workspace: Path,
        *,
        hooks: Hooks | None = None,
        listeners: Sequence[Listener] = (),
        io: ModelIO | None = None,
        options: RunOptions | None = None,
    ) -> None:
        super().__init__(workspace, io=io, options=options)
        self.hooks = hooks if hooks is not None else Hooks()
        self.listeners = listeners

    async def start(self, prompt: str | None) -> None:
        await super().start(prompt)
        await emit(Event("run_start"), self.listeners)

    async def begin_turn(self) -> None:
        await emit(Event("turn_start"), self.listeners)

    async def apply_before_model(
        self, messages: list[ModelMessage]
    ) -> list[ModelMessage]:
        view = await self.hooks.invoke("before_model", messages)
        if not isinstance(view, list):
            raise TypeError("missing model input")
        return view

    async def prepare(self) -> list[ModelMessage]:
        return await self.apply_before_model(await super().prepare())

    async def on_response(self, response: ModelResponse) -> None:
        await super().on_response(response)
        await self.hooks.invoke("after_model", response)
        await emit(Event("model_response"), self.listeners)

    async def execute(self, call: ToolCallPart) -> ToolExecution:
        return await execute_tool(call, self.workspace, self.hooks, self.listeners)

    async def on_result(self, execution: ToolExecution) -> None:
        await super().on_result(execution)
        await emit(
            Event("tool_end", execution.result.outcome, execution.result.tool_call_id),
            self.listeners,
        )

    async def after_turn(self, results: list[ToolReturnPart]) -> None:
        await super().after_turn(results)
        await emit(Event("turn_end"), self.listeners)
        decision = await self.hooks.invoke("after_turn", self.history)
        if isinstance(decision, Decision) and decision.stop:
            raise RunStopped(decision.reason)

    async def finish(self, status: RunStatus, reason: str) -> None:
        await finish_event(f"{status}: {reason}", self.listeners)
```

## 怎样核对

用 `run_agent(prompt, workspace, runtime=HookRuntime(workspace, hooks=你的策略))` 调用同一入口。注册实际路径拒绝策略，观察 denied 不执行；成功读取时核对 Hook 与事件顺序。拒绝也有 tool_end，只有实际执行才有 tool_start。

不新增测试、mock、fixture 或内联自测。代码静态检查与实际模型/故障验收分开记录。

## 完整参考答案

答案只针对本日新增文件。前面各天的答案是被复用的依赖，不在这里再给修改版。

<details>
<summary>参考答案：src/zeta/hooks.py（完整文件）</summary>

```python
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolReturnPart,
    UserPromptPart,
)

from zeta.loop_common import validate_history

type HookName = Literal[
    "before_model", "after_model", "before_tool", "after_tool", "after_turn"
]


@dataclass(frozen=True)
class Decision:
    stop: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ToolContext:
    name: str
    call_id: str
    path: str


type HookContext = list[ModelMessage] | ModelResponse | ToolContext | ToolReturnPart
type HookResult = list[ModelMessage] | ToolReturnPart | Decision | None
type Callback = Callable[[HookContext], Awaitable[HookResult]]


class Hooks:
    def __init__(self) -> None:
        self.callbacks: dict[HookName, list[Callback]] = {
            name: []
            for name in (
                "before_model",
                "after_model",
                "before_tool",
                "after_tool",
                "after_turn",
            )
        }

    def register(self, name: HookName, callback: Callback) -> None:
        if name not in self.callbacks:
            raise ValueError("unknown hook")
        self.callbacks[name].append(callback)

    async def invoke(self, name: HookName, context: HookContext) -> HookResult:
        if name not in self.callbacks:
            raise ValueError("unknown hook")
        current = deepcopy(context)
        for callback in self.callbacks[name]:
            result = await callback(deepcopy(current))
            if result is None:
                continue
            if name == "before_model":
                if not isinstance(current, list) or not isinstance(result, list):
                    raise TypeError("before_model must return a message list")
                if not current or len(result) < len(current):
                    raise ValueError("hook cannot remove the prepared context")
                if result[-len(current) :] != current:
                    raise ValueError("hook cannot rewrite prepared messages")
                for message in result[: -len(current)]:
                    if (
                        not isinstance(message, ModelRequest)
                        or message.instructions
                        or (not message.parts)
                        or (
                            not all(
                                isinstance(p, UserPromptPart) for p in message.parts
                            )
                        )
                    ):
                        raise ValueError(
                            "hook may only prepend user-level context data"
                        )
                validate_history(result)
                current = deepcopy(result)
            elif name == "after_tool":
                if not isinstance(current, ToolReturnPart) or not isinstance(
                    result, ToolReturnPart
                ):
                    raise TypeError("after_tool must return a tool result")
                if (result.tool_name, result.tool_call_id, result.outcome) != (
                    current.tool_name,
                    current.tool_call_id,
                    current.outcome,
                ):
                    raise ValueError("hook changed tool result identity or outcome")
                current = deepcopy(result)
            elif name in ("before_tool", "after_turn"):
                if not isinstance(result, Decision):
                    raise TypeError("decision hook must return Decision")
                if result.stop:
                    if not result.reason.strip():
                        raise ValueError("a stop/deny decision needs a reason")
                    return result
            else:
                raise TypeError("after_model is read-only and must return None")
        if name in ("before_tool", "after_turn"):
            return Decision()
        if name == "after_model":
            return None
        if isinstance(current, (list, ToolReturnPart)):
            return current
        raise TypeError("invalid hook context")
```

</details>

<details>
<summary>参考答案：src/zeta/lifecycle.py（完整文件）</summary>

```python
import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    kind: str
    detail: str = ""
    call_id: str = ""


type Listener = Callable[[Event], Awaitable[None]]


async def emit(event: Event, listeners: Sequence[Listener]) -> None:
    for listener in tuple(listeners):
        try:
            await listener(event)
        except Exception as error:  # noqa: BLE001 - intentional isolation or cleanup
            logger.warning("event listener failed: %s", type(error).__name__)


async def finish_event(status: str, listeners: Sequence[Listener]) -> None:
    try:
        async with asyncio.timeout(1.0):
            await emit(Event("run_end", status), listeners)
    except TimeoutError:
        logger.warning("run_end listeners timed out")
```

</details>

<details>
<summary>参考答案：src/zeta/dispatch.py（完整文件）</summary>

```python
import asyncio
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

from zeta.hooks import Decision, Hooks, ToolContext
from zeta.lifecycle import Event, Listener, emit
from zeta.runtime_base import ToolExecution
from zeta.tools import ReadArgs, ToolError, read_file


async def execute_tool(
    call: ToolCallPart,
    workspace: Path,
    hooks: Hooks,
    listeners: Sequence[Listener] = (),
) -> ToolExecution:
    raw: ToolReturnPart | None = None
    args: ReadArgs | None = None
    try:
        if call.tool_name != "read":
            raise ToolError("unknown tool")
        args = (
            ReadArgs.model_validate_json(call.args)
            if isinstance(call.args, str)
            else ReadArgs.model_validate(call.args)
        )
    except ValidationError, ToolError:
        raw = ToolReturnPart(
            tool_name=call.tool_name,
            tool_call_id=call.tool_call_id,
            content="unknown tool or invalid read arguments",
            outcome="failed",
        )
    if args is not None:
        decision = await hooks.invoke(
            "before_tool", ToolContext(call.tool_name, call.tool_call_id, args.path)
        )
        if not isinstance(decision, Decision):
            raise TypeError("missing tool decision")
        if decision.stop:
            raw = ToolReturnPart(
                tool_name=call.tool_name,
                tool_call_id=call.tool_call_id,
                content=decision.reason,
                outcome="denied",
            )
        else:
            await emit(
                Event("tool_start", call.tool_name, call.tool_call_id), listeners
            )
            try:
                content = await asyncio.to_thread(read_file, args, workspace)
            except ToolError as error:
                raw = ToolReturnPart(
                    tool_name=call.tool_name,
                    tool_call_id=call.tool_call_id,
                    content=str(error),
                    outcome="failed",
                )
            else:
                raw = ToolReturnPart(
                    tool_name=call.tool_name,
                    tool_call_id=call.tool_call_id,
                    content=content,
                )
    if raw is None:
        raise RuntimeError("missing raw tool result")
    result = await hooks.invoke("after_tool", raw)
    if not isinstance(result, ToolReturnPart):
        raise TypeError("missing final tool result")
    return ToolExecution(deepcopy(raw), deepcopy(result))
```

</details>

<details>
<summary>参考答案：src/zeta/hook_runtime.py（完整文件）</summary>

```python
from collections.abc import Sequence
from pathlib import Path

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

from zeta.dispatch import execute_tool
from zeta.hooks import Decision, Hooks
from zeta.lifecycle import Event, Listener, emit, finish_event
from zeta.loop_common import RunStopped
from zeta.runtime_base import ModelIO, RunOptions, RunStatus, Runtime, ToolExecution


class HookRuntime(Runtime):
    def __init__(
        self,
        workspace: Path,
        *,
        hooks: Hooks | None = None,
        listeners: Sequence[Listener] = (),
        io: ModelIO | None = None,
        options: RunOptions | None = None,
    ) -> None:
        super().__init__(workspace, io=io, options=options)
        self.hooks = hooks if hooks is not None else Hooks()
        self.listeners = listeners

    async def start(self, prompt: str | None) -> None:
        await super().start(prompt)
        await emit(Event("run_start"), self.listeners)

    async def begin_turn(self) -> None:
        await emit(Event("turn_start"), self.listeners)

    async def apply_before_model(
        self, messages: list[ModelMessage]
    ) -> list[ModelMessage]:
        view = await self.hooks.invoke("before_model", messages)
        if not isinstance(view, list):
            raise TypeError("missing model input")
        return view

    async def prepare(self) -> list[ModelMessage]:
        return await self.apply_before_model(await super().prepare())

    async def on_response(self, response: ModelResponse) -> None:
        await super().on_response(response)
        await self.hooks.invoke("after_model", response)
        await emit(Event("model_response"), self.listeners)

    async def execute(self, call: ToolCallPart) -> ToolExecution:
        return await execute_tool(call, self.workspace, self.hooks, self.listeners)

    async def on_result(self, execution: ToolExecution) -> None:
        await super().on_result(execution)
        await emit(
            Event("tool_end", execution.result.outcome, execution.result.tool_call_id),
            self.listeners,
        )

    async def after_turn(self, results: list[ToolReturnPart]) -> None:
        await super().after_turn(results)
        await emit(Event("turn_end"), self.listeners)
        decision = await self.hooks.invoke("after_turn", self.history)
        if isinstance(decision, Decision) and decision.stop:
            raise RunStopped(decision.reason)

    async def finish(self, status: RunStatus, reason: str) -> None:
        await finish_event(f"{status}: {reason}", self.listeners)
```

</details>

## 与前后单元的关系

Day 3 用新的 SessionRuntime 包装持久化，仍调用本日 HookRuntime；本日 hooks.py、dispatch.py、lifecycle.py 不修改。
