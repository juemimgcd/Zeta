# Day 7：组装完整 Agent，复用既有循环

[总览](summary.md) · [固定基础代码](support.md)

## 核心问题

把 Day 3–6 的能力连接起来，而不是再写一遍 Agent。今天只实现 ContextRuntime.prepare/retry：选上下文、调用已有压缩、决定溢出后是否重试。请求、工具、Hook、事件、终态仍由前几天完成的代码负责。

## 今天新增什么，哪些文件不动

**今天只新增：** `integration.py`。每个文件的实现只在它所属的这一天给出。

**保留不动：** support.md 的固定基础文件及前面各天已完成的全部文件。今天不替换 app.py，不重新填写 run_agent/run_loop，不复制一份旧循环改名。

## 本日实现与边界

- Services 的字段、ContextRuntime 的初始化、read_summary 和 run_session_task 都提前提供。
- prepare 调用已有 recall/build_context/compact；候选必须变小并降至 65% 目标内，再保存。达到 80% 输入额度时可主动压缩。
- apply_before_model 复用 Day 2，之后再次检查协议与预算；不能为此另实现一套 Hook。
- retry 仅识别明确的上下文长度错误、最多允许一次压缩重试。实际请求计数与继续动作仍属于 run_loop。
- request/summarizer 字段从本文件首次提供时就已存在，Day 8 只传入共享预算包装，不加字段、不改调用点。
- run_session_task 只创建 ContextRuntime 并 await run_loop；没有第二个 while 或工具循环。

## 完整练习骨架

导包、异常类、字段、初始化和辅助实现已给出，只填 TODO 函数体。NotImplementedError 是未完成提示；移除它并填写真实逻辑后再验收。骨架暂时关闭未使用导入提示，其他类型检查保持开启。

### src/zeta/integration.py

只填写：`ContextRuntime.prepare`、`ContextRuntime.retry`。

```python
# ruff: noqa: F401  # Prepared imports for exercise bodies.
# pyright: reportUnusedImport=false
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage

from zeta.compaction import choose_compaction_range, compact
from zeta.context import (
    Budget,
    Resource,
    Summary,
    build_context,
    estimate_tokens,
    uncovered_entries,
)
from zeta.hooks import Hooks
from zeta.lifecycle import Listener
from zeta.loop import run_loop
from zeta.loop_common import INSTRUCTIONS, RunLimitError, validate_history
from zeta.memory import Memory, MemoryStore, recall
from zeta.model_io import request_once, summarize_once
from zeta.runtime_base import ModelIO, RequestFn, RunOptions, SummaryFn
from zeta.session import load_session, save_session
from zeta.session_runtime import SessionRuntime
from zeta.storage import JsonStore


@dataclass
class Services:
    database: JsonStore
    memories: MemoryStore
    workspace: Path
    budget: Budget = field(default_factory=Budget)
    hooks: Hooks = field(default_factory=Hooks)
    listeners: Sequence[Listener] = ()
    resources: Sequence[Resource] = ()
    recall_query: str = ""
    request: RequestFn = request_once
    summarizer: SummaryFn = summarize_once


def read_summary(services: Services, session_id: str) -> Summary | None:
    body = services.database.get("summary", session_id)
    if body is None:
        return None
    summary = Summary.model_validate_json(body)
    for memory_id in summary.memory_ids:
        record = services.database.get("memory", memory_id)
        memory = None if record is None else Memory.model_validate_json(record)
        if (
            memory is None
            or not memory.active
            or memory.scope not in services.memories.allowed_scopes
        ):
            raise ValueError(
                "summary uses forgotten/inaccessible memory; start a fresh session"
            )
    return summary


class ContextRuntime(SessionRuntime):
    def __init__(
        self, session_id: str, services: Services, *, reviewed_resume: bool = False
    ) -> None:
        super().__init__(
            services.database,
            session_id,
            services.workspace,
            allowed_scopes=services.memories.allowed_scopes,
            reviewed_resume=reviewed_resume,
            hooks=services.hooks,
            listeners=services.listeners,
            io=ModelIO(request=services.request, summarize=services.summarizer),
            options=RunOptions(output_tokens=services.budget.output),
        )
        self.services = services
        self.query = services.recall_query
        self.force_compaction = False
        self.overflow_retried = False

    async def start(self, prompt: str | None) -> None:
        await super().start(prompt)
        self.query = self.services.recall_query or prompt or ""

    async def prepare(self) -> list[ModelMessage]:
        """TODO：
        1. 从现有 Session/Memory 模块获取输入。
        2. 调用 ContextBuilder，必要时生成并验证候选摘要。
        3. 复用 before_model，再检查预算和工具配对。
        4. 返回模型视图，不请求模型、不执行工具、不另写循环。"""
        raise NotImplementedError("请完成 ContextRuntime.prepare")

    async def retry(self, error: ModelHTTPError) -> bool:
        """TODO：只对已识别的上下文长度错误设置一次压缩重试标记；请求与次数由既有循环负责。"""
        raise NotImplementedError("请完成 ContextRuntime.retry")


async def run_session_task(
    session_id: str,
    prompt: str | None,
    services: Services,
    *,
    reviewed_resume: bool = False,
) -> str:
    runtime = ContextRuntime(session_id, services, reviewed_resume=reviewed_resume)
    return await run_loop(prompt, runtime)
```

## 怎样核对

构建 Services 并调用 run_session_task，串起召回、工具、压缩、存储与恢复。调试器确认最终仍进入 Day 1 的 run_loop。遗忘关联摘要的记忆后，旧摘要应被拒绝而不是静默复用。

不新增测试、mock、fixture 或内联自测。代码静态检查与实际模型/故障验收分开记录。

## 完整参考答案

答案只针对本日新增文件。前面各天的答案是被复用的依赖，不在这里再给修改版。

<details>
<summary>参考答案：src/zeta/integration.py（完整文件）</summary>

```python
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage

from zeta.compaction import choose_compaction_range, compact
from zeta.context import (
    Budget,
    Resource,
    Summary,
    build_context,
    estimate_tokens,
    uncovered_entries,
)
from zeta.hooks import Hooks
from zeta.lifecycle import Listener
from zeta.loop import run_loop
from zeta.loop_common import INSTRUCTIONS, RunLimitError, validate_history
from zeta.memory import Memory, MemoryStore, recall
from zeta.model_io import request_once, summarize_once
from zeta.runtime_base import ModelIO, RequestFn, RunOptions, SummaryFn
from zeta.session import load_session, save_session
from zeta.session_runtime import SessionRuntime
from zeta.storage import JsonStore


@dataclass
class Services:
    database: JsonStore
    memories: MemoryStore
    workspace: Path
    budget: Budget = field(default_factory=Budget)
    hooks: Hooks = field(default_factory=Hooks)
    listeners: Sequence[Listener] = ()
    resources: Sequence[Resource] = ()
    recall_query: str = ""
    request: RequestFn = request_once
    summarizer: SummaryFn = summarize_once


def read_summary(services: Services, session_id: str) -> Summary | None:
    body = services.database.get("summary", session_id)
    if body is None:
        return None
    summary = Summary.model_validate_json(body)
    for memory_id in summary.memory_ids:
        record = services.database.get("memory", memory_id)
        memory = None if record is None else Memory.model_validate_json(record)
        if (
            memory is None
            or not memory.active
            or memory.scope not in services.memories.allowed_scopes
        ):
            raise ValueError(
                "summary uses forgotten/inaccessible memory; start a fresh session"
            )
    return summary


class ContextRuntime(SessionRuntime):
    def __init__(
        self, session_id: str, services: Services, *, reviewed_resume: bool = False
    ) -> None:
        super().__init__(
            services.database,
            session_id,
            services.workspace,
            allowed_scopes=services.memories.allowed_scopes,
            reviewed_resume=reviewed_resume,
            hooks=services.hooks,
            listeners=services.listeners,
            io=ModelIO(request=services.request, summarize=services.summarizer),
            options=RunOptions(output_tokens=services.budget.output),
        )
        self.services = services
        self.query = services.recall_query
        self.force_compaction = False
        self.overflow_retried = False

    async def start(self, prompt: str | None) -> None:
        await super().start(prompt)
        self.query = self.services.recall_query or prompt or ""

    async def prepare(self) -> list[ModelMessage]:
        services = self.services
        session = load_session(self.database, self.session_id)
        memories = recall(
            services.memories, self.query, services.memories.allowed_scopes
        )
        with self.database.transaction():
            session.memory_ids = sorted(
                set(session.memory_ids) | {memory.id for memory in memories}
            )
            save_session(self.database, session)
        summary = read_summary(services, self.session_id)
        view = build_context(
            INSTRUCTIONS,
            services.resources,
            memories,
            summary,
            session.entries,
            services.budget,
        )
        old_tasks = choose_compaction_range(uncovered_entries(session.entries, summary))
        proactive = bool(old_tasks) and view.estimated_tokens >= int(
            services.budget.input_limit * 0.8
        )
        if self.force_compaction or view.needs_compaction or proactive:
            candidate = await compact(
                session.entries,
                summary,
                self.io.summarize,
                budget=services.budget,
                memory_ids=session.memory_ids,
            )
            candidate_view = build_context(
                INSTRUCTIONS,
                services.resources,
                memories,
                candidate,
                session.entries,
                services.budget,
            )
            if (
                candidate_view.needs_compaction
                or candidate_view.estimated_tokens >= view.estimated_tokens
                or candidate_view.estimated_tokens
                > int(services.budget.input_limit * 0.65)
            ):
                raise ValueError("compaction did not meet the context target")
            with self.database.transaction():
                self.database.put(
                    "summary", self.session_id, candidate.model_dump_json()
                )
            view = candidate_view
            self.force_compaction = False
        request_view = await self.apply_before_model(view.messages)
        validate_history(request_view)
        if estimate_tokens(request_view) > services.budget.input_limit:
            raise RunLimitError("before_model exceeded the input allowance")
        return request_view

    async def retry(self, error: ModelHTTPError) -> bool:
        detail = str(error.body).casefold()
        overflow = error.status_code == 400 and any(
            marker in detail
            for marker in (
                "context_length_exceeded",
                "maximum context length",
                "context window",
            )
        )
        if not overflow or self.overflow_retried:
            return False
        self.overflow_retried = self.force_compaction = True
        return True


async def run_session_task(
    session_id: str,
    prompt: str | None,
    services: Services,
    *,
    reviewed_resume: bool = False,
) -> str:
    runtime = ContextRuntime(session_id, services, reviewed_resume=reviewed_resume)
    return await run_loop(prompt, runtime)
```

</details>

## 与前后单元的关系

Day 8 的 Worker 传入不同 Services 实例及共享请求包装，调用同一个 run_session_task。本日不增加第二个循环；当 Memory/Context/Compaction 需要调整时，应修改它们自己的策略而不是复制 Loop。
