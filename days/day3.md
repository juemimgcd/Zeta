# Day 3：新增 Session 持久化与恢复

[总览](summary.md) · [固定基础代码](support.md)

## 核心问题

如何持久化完整事实、识别未完成批次并安全恢复？只写 Session 策略；配套 SessionRuntime 在提交后调用 Day 2 的处理，不复制 Loop、Hook 或工具实现。

## 今天新增什么，哪些文件不动

**今天只新增：** `session.py`、`session_runtime.py`。每个文件的实现只在它所属的这一天给出。

**保留不动：** support.md 的固定基础文件及前面各天已完成的全部文件。今天不替换 app.py，不重新填写 run_agent/run_loop，不复制一份旧循环改名。

## 本日实现与边界

- Session 中保留稳定 entry_id、有序 entries、pending、scope 和终态，存储底层使用 support.md 的 JsonStore。
- commit_response 保存完整响应和 pending，但不能提前把 run 标为 completed；最后 Hook 仍可能失败。
- commit_tool_result 同事务保存 raw/result 并移除 pending，重复或错配结果拒绝。
- history_messages 将逐项保存的工具结果重组成完整批次；load_resume_point 只返回恢复决策，不自动执行调用。
- session_runtime.py 直接提供：先提交，再调用 HookRuntime 已有行为。未取得该 run 的处理权时，拒绝恢复不会改写原 Session 状态。

## 完整练习骨架

导包、异常类、字段、初始化和辅助实现已给出，只填 TODO 函数体。NotImplementedError 是未完成提示；移除它并填写真实逻辑后再验收。骨架暂时关闭未使用导入提示，其他类型检查保持开启。

### src/zeta/session.py

只填写：`append_user`、`commit_response`、`commit_tool_result`、`finish_session`、`history_messages`、`load_resume_point`。

```python
# ruff: noqa: F401  # Prepared imports for exercise bodies.
# pyright: reportUnusedImport=false
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

from zeta.loop_common import INSTRUCTIONS, response_calls, validate_history
from zeta.storage import JsonStore


class Entry(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    message_json: str
    raw_json: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class SessionData(BaseModel):
    id: str
    scope: str
    entries: list[Entry] = Field(default_factory=list[Entry])
    pending: dict[str, str] = Field(default_factory=dict)
    status: Literal[
        "ready", "running", "completed", "stopped", "failed", "cancelled"
    ] = "ready"
    reason: str = ""
    memory_ids: list[str] = Field(default_factory=list[str])


def encode(messages: Sequence[ModelMessage]) -> str:
    return ModelMessagesTypeAdapter.dump_json(list(messages)).decode("utf-8")


def decode(entry: Entry) -> ModelMessage:
    messages = ModelMessagesTypeAdapter.validate_json(entry.message_json)
    if len(messages) != 1:
        raise ValueError("an entry must contain exactly one message")
    return messages[0]


def load_session(store: JsonStore, session_id: str) -> SessionData:
    body = store.get("session", session_id)
    if body is None:
        raise KeyError("unknown session")
    return SessionData.model_validate_json(body)


def save_session(store: JsonStore, session: SessionData) -> None:
    store.put("session", session.id, session.model_dump_json())


def create_session(store: JsonStore, scope: str) -> str:
    if not scope.strip():
        raise ValueError("scope is required")
    session = SessionData(id=uuid4().hex, scope=scope)
    with store.transaction():
        save_session(store, session)
    return session.id


def append_user(store: JsonStore, session_id: str, prompt: str) -> str:
    """TODO：按本日契约实现 append_user，写完与下方同名函数逐分支核对。"""
    raise NotImplementedError("请完成 append_user")


def commit_response(store: JsonStore, session_id: str, response: ModelResponse) -> str:
    """TODO：
    1. 校验响应并加载运行中的 Session。
    2. 拒绝 pending 未清或上一条不是请求的状态。
    3. 在同一事务追加完整响应和 pending，不提前标完成。"""
    raise NotImplementedError("请完成 commit_response")


def commit_tool_result(
    store: JsonStore,
    session_id: str,
    result: ToolReturnPart,
    raw: ToolReturnPart | None = None,
) -> str:
    """TODO：
    1. 校验 raw/result 的 ID、名称和状态一致。
    2. 确认调用仍在 pending，拒绝重复提交。
    3. 保存原始及最终结果，移除 pending 并提交事务。"""
    raise NotImplementedError("请完成 commit_tool_result")


def finish_session(
    store: JsonStore,
    session_id: str,
    status: Literal["completed", "stopped", "failed", "cancelled"],
    reason: str = "",
) -> None:
    """TODO：按本日契约实现 finish_session，写完与下方同名函数逐分支核对。"""
    raise NotImplementedError("请完成 finish_session")


def history_messages(entries: Sequence[Entry]) -> list[ModelMessage]:
    """TODO：按本日契约实现 history_messages，写完与下方同名函数逐分支核对。"""
    raise NotImplementedError("请完成 history_messages")


class ResumePoint(BaseModel):
    session: SessionData
    action: Literal["new_input", "continue", "resolve_pending", "review"]


def load_resume_point(store: JsonStore, session_id: str) -> ResumePoint:
    """TODO：
    1. 加载 Session，优先识别 pending。
    2. 区分新输入、可续接、需处理调用及需人工复核。
    3. 只返回恢复决策，不执行工具或模型。"""
    raise NotImplementedError("请完成 load_resume_point")


def pending_calls(session: SessionData) -> list[ToolCallPart]:
    for entry in reversed(session.entries):
        message = decode(entry)
        if isinstance(message, ModelResponse):
            return [
                call
                for call in response_calls(message)
                if call.tool_call_id in session.pending
            ]
    return []
```

### src/zeta/session_runtime.py

直接提供的接入代码，原样使用；内部调用前面已完成的方法，不重新实现它们。

```python
from collections.abc import Sequence
from pathlib import Path

from pydantic_ai.messages import ModelResponse

from zeta.hook_runtime import HookRuntime
from zeta.hooks import Hooks
from zeta.lifecycle import Event, Listener, emit
from zeta.runtime_base import ModelIO, RunOptions, RunStatus, ToolExecution
from zeta.session import (
    append_user,
    commit_response,
    commit_tool_result,
    decode,
    finish_session,
    history_messages,
    load_resume_point,
    load_session,
    save_session,
)
from zeta.storage import JsonStore


class SessionRuntime(HookRuntime):
    """Supplied adapter: persistence precedes HookRuntime's observation hooks."""

    def __init__(
        self,
        database: JsonStore,
        session_id: str,
        workspace: Path,
        *,
        allowed_scopes: frozenset[str],
        reviewed_resume: bool = False,
        hooks: Hooks | None = None,
        listeners: Sequence[Listener] = (),
        io: ModelIO | None = None,
        options: RunOptions | None = None,
    ) -> None:
        super().__init__(
            workspace, hooks=hooks, listeners=listeners, io=io, options=options
        )
        self.database = database
        self.session_id = session_id
        self.allowed_scopes = allowed_scopes
        self.reviewed_resume = reviewed_resume
        self.owns_run = False

    async def start(self, prompt: str | None) -> None:
        if self.started:
            raise ValueError("create a fresh Runtime to resume")
        point = load_resume_point(self.database, self.session_id)
        if point.session.scope not in self.allowed_scopes:
            raise PermissionError("session belongs to another scope")
        if point.action == "resolve_pending":
            raise ValueError("resolve pending calls explicitly")
        if prompt is not None:
            if point.action != "new_input":
                raise ValueError("finish or review the previous task first")
            append_user(self.database, self.session_id, prompt)
        else:
            if point.action == "new_input":
                raise ValueError("new user input is required")
            if point.action == "review" and not self.reviewed_resume:
                raise ValueError("explicit resume review required")
            if point.session.entries and isinstance(
                decode(point.session.entries[-1]), ModelResponse
            ):
                raise ValueError(
                    "review terminal hook failure; final answer already exists"
                )
            with self.database.transaction():
                session = load_session(self.database, self.session_id)
                session.status, session.reason = "running", ""
                save_session(self.database, session)
        self.started = self.owns_run = True
        self.history = history_messages(
            load_session(self.database, self.session_id).entries
        )
        await emit(Event("run_start"), self.listeners)

    async def on_response(self, response: ModelResponse) -> None:
        commit_response(self.database, self.session_id, response)
        await super().on_response(response)

    async def on_result(self, execution: ToolExecution) -> None:
        commit_tool_result(
            self.database, self.session_id, execution.result, execution.raw
        )
        await super().on_result(execution)

    async def finish(self, status: RunStatus, reason: str) -> None:
        try:
            if self.owns_run:
                finish_session(self.database, self.session_id, status, reason)
        finally:
            await super().finish(status, reason)
```

## 怎样核对

创建 JsonStore 和 SessionRuntime，用 Day 1 的 `run_loop(prompt, runtime)` 跑任务。记录 session_id，重启后创建新的 SessionRuntime 并传 prompt=None 恢复。pending 或 review 未处理时必须停止；没有实际故障恢复证据就标记未验证。

不新增测试、mock、fixture 或内联自测。代码静态检查与实际模型/故障验收分开记录。

## 完整参考答案

答案只针对本日新增文件。前面各天的答案是被复用的依赖，不在这里再给修改版。

<details>
<summary>参考答案：src/zeta/session.py（完整文件）</summary>

```python
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

from zeta.loop_common import INSTRUCTIONS, response_calls, validate_history
from zeta.storage import JsonStore


class Entry(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    message_json: str
    raw_json: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class SessionData(BaseModel):
    id: str
    scope: str
    entries: list[Entry] = Field(default_factory=list[Entry])
    pending: dict[str, str] = Field(default_factory=dict)
    status: Literal[
        "ready", "running", "completed", "stopped", "failed", "cancelled"
    ] = "ready"
    reason: str = ""
    memory_ids: list[str] = Field(default_factory=list[str])


def encode(messages: Sequence[ModelMessage]) -> str:
    return ModelMessagesTypeAdapter.dump_json(list(messages)).decode("utf-8")


def decode(entry: Entry) -> ModelMessage:
    messages = ModelMessagesTypeAdapter.validate_json(entry.message_json)
    if len(messages) != 1:
        raise ValueError("an entry must contain exactly one message")
    return messages[0]


def load_session(store: JsonStore, session_id: str) -> SessionData:
    body = store.get("session", session_id)
    if body is None:
        raise KeyError("unknown session")
    return SessionData.model_validate_json(body)


def save_session(store: JsonStore, session: SessionData) -> None:
    store.put("session", session.id, session.model_dump_json())


def create_session(store: JsonStore, scope: str) -> str:
    if not scope.strip():
        raise ValueError("scope is required")
    session = SessionData(id=uuid4().hex, scope=scope)
    with store.transaction():
        save_session(store, session)
    return session.id


def append_user(store: JsonStore, session_id: str, prompt: str) -> str:
    if not prompt.strip():
        raise ValueError("empty prompt")
    with store.transaction():
        session = load_session(store, session_id)
        if session.pending or session.status == "running":
            raise ValueError("finish or explicitly resolve the existing run first")
        if session.entries:
            last = decode(session.entries[-1])
            if not isinstance(last, ModelResponse) or response_calls(last):
                raise ValueError("previous task has no final response")
        entry = Entry(
            message_json=encode(
                [ModelRequest.user_text_prompt(prompt, instructions=INSTRUCTIONS)]
            )
        )
        session.entries.append(entry)
        session.status, session.reason = ("running", "")
        save_session(store, session)
    return entry.id


def commit_response(store: JsonStore, session_id: str, response: ModelResponse) -> str:
    calls = response_calls(response)
    with store.transaction():
        session = load_session(store, session_id)
        if session.pending or session.status != "running":
            raise ValueError("session is not ready for a response")
        if not session.entries or not isinstance(
            decode(session.entries[-1]), ModelRequest
        ):
            raise ValueError("response must follow user input or a tool-result batch")
        entry = Entry(message_json=encode([response]))
        session.entries.append(entry)
        session.pending = {call.tool_call_id: call.tool_name for call in calls}
        save_session(store, session)
    return entry.id


def commit_tool_result(
    store: JsonStore,
    session_id: str,
    result: ToolReturnPart,
    raw: ToolReturnPart | None = None,
) -> str:
    original = result if raw is None else raw
    if (result.tool_name, result.tool_call_id, result.outcome) != (
        original.tool_name,
        original.tool_call_id,
        original.outcome,
    ):
        raise ValueError("raw and final result disagree")
    with store.transaction():
        session = load_session(store, session_id)
        if session.pending.get(result.tool_call_id) != result.tool_name:
            raise ValueError("unknown or already committed tool result")
        entry = Entry(
            message_json=encode(
                [ModelRequest(parts=[result], instructions=INSTRUCTIONS)]
            ),
            raw_json=encode(
                [ModelRequest(parts=[original], instructions=INSTRUCTIONS)]
            ),
        )
        session.entries.append(entry)
        del session.pending[result.tool_call_id]
        save_session(store, session)
    return entry.id


def finish_session(
    store: JsonStore,
    session_id: str,
    status: Literal["completed", "stopped", "failed", "cancelled"],
    reason: str = "",
) -> None:
    with store.transaction():
        session = load_session(store, session_id)
        if status == "completed" and session.pending:
            raise ValueError("cannot complete a pending batch")
        session.status, session.reason = (status, reason)
        save_session(store, session)


def history_messages(entries: Sequence[Entry]) -> list[ModelMessage]:
    """Reassemble separately committed results into complete request batches."""
    messages: list[ModelMessage] = []
    batch: list[ToolReturnPart] = []
    for entry in entries:
        message = decode(entry)
        if isinstance(message, ModelRequest) and all(
            isinstance(part, ToolReturnPart) for part in message.parts
        ):
            batch.extend(
                part for part in message.parts if isinstance(part, ToolReturnPart)
            )
        else:
            if batch:
                messages.append(
                    ModelRequest(parts=list(batch), instructions=INSTRUCTIONS)
                )
                batch.clear()
            messages.append(message)
    if batch:
        messages.append(ModelRequest(parts=batch, instructions=INSTRUCTIONS))
    validate_history(messages)
    return messages


class ResumePoint(BaseModel):
    session: SessionData
    action: Literal["new_input", "continue", "resolve_pending", "review"]


def load_resume_point(store: JsonStore, session_id: str) -> ResumePoint:
    session = load_session(store, session_id)
    if session.pending:
        action = "resolve_pending"
    elif not session.entries:
        action = "new_input"
    elif session.status in ("failed", "cancelled", "stopped"):
        action = "review"
    else:
        history_messages(session.entries)
        last = decode(session.entries[-1])
        action = (
            "review"
            if isinstance(last, ModelResponse) and session.status == "running"
            else "new_input"
            if isinstance(last, ModelResponse)
            else "continue"
        )
    return ResumePoint(session=session, action=action)


def pending_calls(session: SessionData) -> list[ToolCallPart]:
    for entry in reversed(session.entries):
        message = decode(entry)
        if isinstance(message, ModelResponse):
            return [
                call
                for call in response_calls(message)
                if call.tool_call_id in session.pending
            ]
    return []
```

</details>

<details>
<summary>参考答案：src/zeta/session_runtime.py（完整文件）</summary>

```python
from collections.abc import Sequence
from pathlib import Path

from pydantic_ai.messages import ModelResponse

from zeta.hook_runtime import HookRuntime
from zeta.hooks import Hooks
from zeta.lifecycle import Event, Listener, emit
from zeta.runtime_base import ModelIO, RunOptions, RunStatus, ToolExecution
from zeta.session import (
    append_user,
    commit_response,
    commit_tool_result,
    decode,
    finish_session,
    history_messages,
    load_resume_point,
    load_session,
    save_session,
)
from zeta.storage import JsonStore


class SessionRuntime(HookRuntime):
    """Supplied adapter: persistence precedes HookRuntime's observation hooks."""

    def __init__(
        self,
        database: JsonStore,
        session_id: str,
        workspace: Path,
        *,
        allowed_scopes: frozenset[str],
        reviewed_resume: bool = False,
        hooks: Hooks | None = None,
        listeners: Sequence[Listener] = (),
        io: ModelIO | None = None,
        options: RunOptions | None = None,
    ) -> None:
        super().__init__(
            workspace, hooks=hooks, listeners=listeners, io=io, options=options
        )
        self.database = database
        self.session_id = session_id
        self.allowed_scopes = allowed_scopes
        self.reviewed_resume = reviewed_resume
        self.owns_run = False

    async def start(self, prompt: str | None) -> None:
        if self.started:
            raise ValueError("create a fresh Runtime to resume")
        point = load_resume_point(self.database, self.session_id)
        if point.session.scope not in self.allowed_scopes:
            raise PermissionError("session belongs to another scope")
        if point.action == "resolve_pending":
            raise ValueError("resolve pending calls explicitly")
        if prompt is not None:
            if point.action != "new_input":
                raise ValueError("finish or review the previous task first")
            append_user(self.database, self.session_id, prompt)
        else:
            if point.action == "new_input":
                raise ValueError("new user input is required")
            if point.action == "review" and not self.reviewed_resume:
                raise ValueError("explicit resume review required")
            if point.session.entries and isinstance(
                decode(point.session.entries[-1]), ModelResponse
            ):
                raise ValueError(
                    "review terminal hook failure; final answer already exists"
                )
            with self.database.transaction():
                session = load_session(self.database, self.session_id)
                session.status, session.reason = "running", ""
                save_session(self.database, session)
        self.started = self.owns_run = True
        self.history = history_messages(
            load_session(self.database, self.session_id).entries
        )
        await emit(Event("run_start"), self.listeners)

    async def on_response(self, response: ModelResponse) -> None:
        commit_response(self.database, self.session_id, response)
        await super().on_response(response)

    async def on_result(self, execution: ToolExecution) -> None:
        commit_tool_result(
            self.database, self.session_id, execution.result, execution.raw
        )
        await super().on_result(execution)

    async def finish(self, status: RunStatus, reason: str) -> None:
        try:
            if self.owns_run:
                finish_session(self.database, self.session_id, status, reason)
        finally:
            await super().finish(status, reason)
```

</details>

## 与前后单元的关系

Day 4–6 新增数据策略；Day 7 通过新文件 integration.py 调用它们。本日提交/恢复函数和接入层不修改。单进程存储不保证外部副作用恰好执行一次，pending 不自动重放。
