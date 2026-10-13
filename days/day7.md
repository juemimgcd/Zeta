# Day 7：组装完整 Agent，复用既有循环

[总览](summary.md) · [固定基础代码](support.md)

本日补全的是基础组装版，延续 Day 5–6 的完整任务压缩边界。按 token 保留、长任务内部切分和分批摘要见 [Compaction 优化方案](compaction-optimization.md)，不把尚未实现的进阶能力写进本日参考答案。

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
- request/summarizer 字段从本文件首次提供时就已存在，Day 9 只传入共享预算包装，不加字段、不改调用点。
- run_session_task 只创建 ContextRuntime 并 await run_loop；没有第二个 while 或工具循环。

## 先认识本日的类与函数

| 类 | 它是什么 | 属性是什么意思 |
| --- | --- | --- |
| `Services` | 集中保存运行依赖的对象 | `database`：会话/摘要存储；`memories`：MemoryStore；`workspace`：工具目录；`budget`：上下文预算；`hooks`：回调管理器；`listeners`：事件监听函数；`resources`：参考资料；`recall_query`：显式检索文本；`request`：单次请求函数；`summarizer`：摘要函数 |
| `ContextRuntime` | 继承 SessionRuntime，加入检索、上下文选择和压缩 | 新增 `services`：依赖集合；`query`：本次检索文本；`force_compaction`：下次 prepare 是否强制压缩；`overflow_retried`：是否用过超限重试机会 |

继承的 database/session_id/allowed_scopes/owns_run 见 [Day 3](day3.md#先认识本日的类与函数)，hooks/listeners 见 [Day 2](day2.md#先认识本日的类与函数)，history/io/options 等见 [基础代码](support.md#先认识基础代码中的类与函数)。super() 调用父类方法，操作的仍是当前同一个对象。

| 函数或方法 | 输入、功能和返回值 |
| --- | --- |
| `read_summary(services, session_id)` | 读取摘要并检查关联记忆仍存在、有效且可访问；返回 Summary，无摘要返回 None，失效则报错 |
| `ContextRuntime.__init__(session_id, services)` | 把存储、Hook、模型函数和输出预算接入父类，初始化查询和压缩标志 |
| `ContextRuntime.start(prompt)` | 先执行父类启动/恢复，再确定 query：优先 recall_query，其次 prompt，否则空串；返回 None |
| `ContextRuntime.prepare()` | 读会话、recall 并记录记忆来源、读摘要、build_context；必要时 compact、重建并验证后保存摘要；最后 before_model 并复验历史/预算，返回消息列表 |
| `ContextRuntime.retry(error)` | 识别特定 400 上下文超限错误，首次命中设置压缩及重试标志并返回 True，否则 False；本方法不发送请求 |
| `run_session_task(session_id, prompt, services)` | 创建 ContextRuntime 并调用同一个 run_loop，返回最终回答；prompt=None 表示尝试恢复 |

`Services.request` 默认保存 `request_once`，由 Loop 发起带已注册工具的请求；`Services.summarizer` 默认保存 `summarize_once`，内部显式使用空工具序列。Day 9 可以替换这两个函数以加入共享预算，`ModelIO` 和本日组装接口不需要改变。

prepare 中的 `view` 是当前视图，`candidate` 是候选摘要，`candidate_view` 是使用新摘要重建的视图，`request_view` 是 Hook 处理后的最终消息列表。候选验证通过才保存。

## 一次请求怎样串起来

```text
run_session_task(session_id, prompt, services)
  → 创建 ContextRuntime
  → 进入 Day 1 的 run_loop
      → start：检查 Session 范围、pending 和启动/恢复条件
      → prepare：召回 → 构建 Context → 必要时压缩 → before_model
      → 请求模型
      → on_response：保存 assistant 响应及 pending 调用
      → execute / on_result：执行工具，逐条保存结果
      → after_turn：复用 HookRuntime 的后处理
      → 有工具调用则继续下一轮；否则返回最终回答
      → finish：保存终态并完成父类清理
```

ContextRuntime 不覆盖 `on_response`、`execute`、`on_result` 和 `finish`，这些行为继续来自 SessionRuntime / HookRuntime。不要在 prepare 内手动调用工具或把响应再保存一次。

`prepare` 从数据库读取 Session，是为了使用已经提交的完整历史；返回值只用于本次模型请求，不把被裁剪的视图写回 `session.entries`。原历史、摘要和本轮消息视图是三个不同对象。

## prepare 的实现顺序

1. **读取会话并召回记忆。** 使用可信 `allowed_scopes` 调用 recall。把召回记忆的 ID 合入 `session.memory_ids`，再读取摘要并检查其来源记忆是否仍有效。
2. **构建初始 Context。** 固定指令、资源、记忆、旧摘要和 Session 历史一起交给 Day 5 的 build_context，不在这里复制选择算法。
3. **判断是否压缩。** 任一条件成立即可：上一次请求超限后设置了 `force_compaction`；view 标记 `needs_compaction`；存在可压缩旧任务且当前估算达到输入额度的 80%。
4. **生成并验收候选。** Day 6 的 compact 只返回候选。用候选重建 Context，要求不再遗漏待摘要历史、估算严格小于原 view，并且不高于输入额度的 65%。通过后才写入 summary。
5. **执行 Hook 后复验。** apply_before_model 可能改变消息，所以再次检查工具配对和输入额度，最后返回 request_view。

`session.memory_ids` 在本版是“曾召回记忆”的保守集合，不是“本轮真正纳入 Context”的精确集合。即使某条记忆因预算未被选中，其 ID 也可能进入摘要依赖；遗忘它可能导致摘要被拒绝。精细来源追踪属于后续改进。

`needs_compaction=True` 表示旧历史暂时未放入视图，不能直接把该视图发送给模型。本版先把旧历史压成摘要，再重新构建。若 build_context 已经因近期必需内容过大而抛错，就无法进入该分支；这是基础版限制。

## retry 为什么只设置标记

例如第一次请求返回 HTTP 400，错误正文包含 `context_length_exceeded`：

```text
run_loop 捕获 APIStatusError
  → 确认还有请求次数
  → retry 返回 True，并设置 force_compaction / overflow_retried
  → run_loop 回到下一轮 prepare
  → prepare 压缩并验收
  → run_loop 再请求模型
```

retry 不调用模型，也不在内部重新运行 Loop。`overflow_retried` 在当前 Runtime 内只允许一次恢复；成功压缩只清除 `force_compaction`，不重置重试机会。第二次超限、其他 HTTP 状态或无法识别的错误交回 Loop 失败处理。

这里识别的是 HTTP 400 加错误正文关键词，不是所有供应商错误格式的通用识别器。压缩没有可用范围或未达到目标时，prepare 直接失败，不能声称“所有超限都可恢复”。

这次重试只重新请求模型，不重新执行已提交结果的工具。运行总时限仍由 Loop 控制；本版主请求计数不包含独立摘要调用，Day 9 的共享包装才把摘要也纳入共享调用预算。

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

from langchain_core.messages import BaseMessage
from openai import APIStatusError

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
    def __init__(self, session_id: str, services: Services) -> None:
        super().__init__(
            services.database,
            session_id,
            services.workspace,
            allowed_scopes=services.memories.allowed_scopes,
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

    async def prepare(self) -> list[BaseMessage]:
        """TODO：
        1. 从现有 Session/Memory 模块获取输入。
        2. 调用 ContextBuilder，必要时生成并验证候选摘要。
        3. 复用 before_model，再检查预算和工具配对。
        4. 返回模型视图，不请求模型、不执行工具、不另写循环。"""
        raise NotImplementedError("请完成 ContextRuntime.prepare")

    async def retry(self, error: APIStatusError) -> bool:
        """TODO：只对已识别的上下文长度错误设置一次压缩重试标记；请求与次数由既有循环负责。"""
        raise NotImplementedError("请完成 ContextRuntime.retry")


async def run_session_task(
    session_id: str,
    prompt: str | None,
    services: Services,
) -> str:
    runtime = ContextRuntime(session_id, services)
    return await run_loop(prompt, runtime)
```

## 怎样核对

完成练习后，使用同一个 JsonStore 构造 MemoryStore 和 Services，并调用 create_session 创建属于可信 scope 的会话。workspace 必须是实际存在的工具工作目录。

- 新任务传 `run_session_task(session_id, prompt, services)`；已经完成的会话可以在同一 ID 上追加新任务。
- 显式恢复传 `prompt=None`，仅在没有 pending 工具且历史末尾为用户输入或完整工具结果批次时允许。它不是通用的中断工具重放入口。
- 恢复时若仍需记忆召回，应传入合适的 `recall_query`；默认 `prompt=None` 会使查询为空，本版不会自动提取原任务作为查询。
- Session 与 Memory 使用同一个 database，allowed_scopes 由可信调用方提供；不要让模型决定访问范围。
- 当前 CLI 默认使用基础 Runtime，运行 `zeta -p ...` 不能证明本日 ContextRuntime 已接入。调试器应确认进入 run_session_task 和同一个 run_loop。

| 场景 | 需要观察的结果 |
| --- | --- |
| 普通短任务 | 无不必要压缩，最终消息通过配对和预算检查 |
| 长历史达到主动触发条件 | 有旧完整任务才主动压缩；候选通过后才更新 summary |
| Context 标记旧历史未纳入 | 必须先摘要并重建，不能直接发送不完整视图 |
| 候选为空、未缩小或超过 65% | 不覆盖原 summary；失败原因向 Loop 传播，Session 终态可改变 |
| 当前任务本身超预算 | 明确失败，记录为基础版不支持，不把报错当作压缩成功 |
| before_model 增加过多消息或破坏配对 | 最终检查拒绝发送；先前已提交的有效摘要不会因此回滚 |
| 第一次明确的上下文超限 | 在剩余请求预算内，最多允许一次压缩后的模型重试 |
| 摘要依赖的记忆被遗忘或不可访问 | read_summary 拒绝旧摘要，不静默复用 |
| 历史存在未提交工具结果 | start 拒绝恢复，不自动重放可能有副作用的调用 |

没有真实长历史时，压缩质量和恢复效果标为未验证。参考答案仍依赖前几天的源码正确完成，文档补全不代表现有 src 的完整链路已验收。

不新增测试、mock、fixture 或内联自测。代码静态检查与实际模型/故障验收分开记录。

## 完整参考答案

答案只针对本日新增文件。前面各天的答案是被复用的依赖，不在这里再给修改版。

<details>
<summary>参考答案：src/zeta/integration.py（完整文件）</summary>

```python
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import BaseMessage
from openai import APIStatusError

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
    def __init__(self, session_id: str, services: Services) -> None:
        super().__init__(
            services.database,
            session_id,
            services.workspace,
            allowed_scopes=services.memories.allowed_scopes,
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

    async def prepare(self) -> list[BaseMessage]:
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

    async def retry(self, error: APIStatusError) -> bool:
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
) -> str:
    runtime = ContextRuntime(session_id, services)
    return await run_loop(prompt, runtime)
```

</details>

## 与前后单元的关系

Day 8 使用基础 Runtime 接入只读 MCP 工具；Day 9 的 Worker 传入不同 Services 实例及共享请求包装，调用同一个 run_session_task。本日不增加第二个循环；当 Memory/Context/Compaction 需要调整时，应修改它们自己的策略而不是复制 Loop。

## 基础版之后再优化什么

本日保留 Day 5–6 的简化策略：字节启发式估算、完整任务切分、80% 主动触发、65% 硬性验收、一次摘要请求。它能说明如何组装，但不保证长任务始终可以继续。

后续按 [Compaction 优化方案](compaction-optimization.md) 分阶段调整：先修预算与触发顺序，再支持当前任务内部安全切分，最后加入分批摘要和提交一致性检查。这些变化涉及已有模块契约，不能只把 prepare 的阈值改小就算完成。

另外，当前摘要函数仅检查消息/工具调用后返回文本，没有显式检查生成长度截断；摘要失败的原状态保护，也不等于“部分摘要绝不会被接收”。完成原因与 usage 返回契约需要在进阶阶段补齐。
