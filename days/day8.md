# Day 8：Celery + Redis 轻量工具任务队列

[总览](summary.md) · [固定基础代码](support.md) · [下一天：Manager / Worker](day9.md)

## 核心问题

怎样把工具交给独立的 Celery Worker 执行，同时保留 Zeta 已有的 Agent Loop、Hooks、工具结果配对和 Session 保存？

今天做一个单机版本：一个 Redis 实例、一条工具队列、一个 Celery Worker。先让现有 `read` 走通“提交 → 执行 → 返回结果 → 模型继续回答”。Redis 同时承担 Broker 和 Result Backend；SQLite 仍由 Zeta 主进程管理。

本文是学习任务和参考实现，不代表 `src` 已接入 Celery。Day 9 保留原有 Manager / Worker 多 Agent 课程。

## 先区分三个概念

| 概念 | 在本项目中的含义 |
| --- | --- |
| 异步等待 | 主进程等待工具时，事件循环可以处理其他协程 |
| 工具并发 | 同时执行多个工具；当前 `run_loop` 逐个 await，本课保留这个顺序 |
| 队列执行 | 主进程发送任务，独立 Worker 从 Redis 取任务并执行 |

Celery 的 `apply_async()` 是发送任务的方法名，它本身是同步 Python 调用，不是可以直接 await 的协程。Redis 网络操作也可能阻塞，所以提交和等待结果都放到 `asyncio.to_thread()` 中。

即使 Worker 能同时执行多个任务，`for call in calls: await runtime.execute(call)` 仍然是串行派发。本课验证执行进程的分离；同一批独立只读工具的并发是后续改动。

Celery Worker 是执行工具的进程；Day 9 的 Worker 是拥有 Session 和模型循环的子 Agent，两者不是同一个对象。

## 调用链与职责

```text
Zeta 主进程
  run_loop
    → on_response：保存模型响应和 pending 工具调用
    → QueueRuntime.execute
        → dispatch.execute_tool
            → resolve_tool_call：校验名称与参数
            → before_tool：权限与审批
            → execute_queued：生成 Celery task ID，提交 JSON 任务
                         ↓
                    Redis Broker
                         ↓
                Celery Worker：run_tool_job
                    → 再次校验任务与工作区
                    → 复用 TOOLS 中的 read 函数
                    → 返回 JSON 结果
                         ↓
                  Redis Result Backend
                         ↓
            → 取回内容，沿用原 tool_call_id 构造 ToolMessage
            → after_tool：处理结果
    → on_result：保存 raw/result，清除对应 pending
    → after_turn：补齐历史
    → 请求下一轮模型
```

Worker 不接收 Runtime、Hooks、SQLite 连接或 Python 函数。消息只传可 JSON 序列化的数据。Worker 和主进程使用同一份代码、同一个本地工作区；这不是远程工作区同步方案。

## 今天需要写什么

| 文件 | 职责 |
| --- | --- |
| 新增 `src/zeta/celery_app.py` | Redis 地址、队列名、序列化和连接超时 |
| 新增 `src/zeta/queue_tools.py` | 任务/结果格式、Worker 执行函数、主进程调用函数 |
| 新增 `src/zeta/queue_runtime.py` | 继承 ContextRuntime，选择队列执行 |
| 小改 `src/zeta/dispatch.py` | 增加可选 `runner` 参数，复用已有校验和 Hooks |

本课对前面“只新增文件”的规则做一个明确的小调整：为 Day 2 调度器增加一个默认关闭的执行入口。老调用方不传 `runner`，仍然走原来的线程执行；这样不用复制整套审批和结果处理逻辑。下面只展示需要改的部分。

`run_loop`、`HookRuntime`、`SessionRuntime`、`ContextRuntime`、工具注册表和现有工具函数都沿用。本文不会直接修改它们；实际练习时只按下面列出的范围实施。

## 依赖与本地环境

项目使用 Python 3.14。Celery 5.6 开始提供 Python 3.14 的初步支持；本课以 5.6 系列 API 为基线。完成练习时再执行依赖安装，并提交由包管理器生成的锁文件变更：

```zsh
uv add 'celery[redis]>=5.6.3,<5.7'
```

需要本地 Redis。若未安装，可使用 `brew install redis`。三个终端均从 Zeta 项目根目录开始。主进程和 Worker 的环境变量保持一致：

```zsh
export ZETA_QUEUE_WORKSPACE="$PWD"
export ZETA_CELERY_BROKER_URL='redis://127.0.0.1:6379/0'
export ZETA_CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/1'
```

`/0` 和 `/1` 是同一 Redis 实例的两个逻辑数据库，不是两个服务。示例假定这是可信的本机专用 Redis。

## 先认识本日对象与函数

| 对象或函数 | 输入、职责和输出 |
| --- | --- |
| `ToolJob` | 工具名、参数、调用 ID、工作区和最晚开始时间；通过 JSON 跨进程传递 |
| `ToolReply` | 工具名、调用 ID、成功/失败和正文；主进程校验后再使用 |
| `configured_workspace()` | 读取本机工作区配置，返回已解析的目录路径 |
| `run_tool_job(payload)` | Celery task；重新校验，调用现有工具函数，返回 JSON 字典 |
| `execute_queued(call, workspace)` | 主进程异步入口；发送任务、等待结果、核对身份，返回正文或抛异常 |
| `QueueRuntime.execute(call)` | 把 `execute_queued` 交给原有调度器，返回 ToolExecution |
| `run_queued_session(session_id, prompt, services)` | 创建 QueueRuntime，再进入唯一的 run_loop |

`tool_call_id` 用于模型协议配对；Celery `task_id` 用于定位一次队列任务。两者用途不同。本课每次提交生成独立 task ID 并记录日志；不把同一个 task ID 当作自动去重机制。

## 练习顺序

1. 先阅读下面的三个新模块和调度器改动。
2. 配置与数据模型可直接采用参考代码；先隐藏 `run_tool_job` 和 `execute_queued` 的函数体，自己完成这两个函数。
3. `run_tool_job` 按“任务校验 → 工作区校验 → 过期检查 → 工具执行 → 结果封装”实现。
4. `execute_queued` 按“生成身份 → 有界发送/等待 → 结果校验 → 返回正文”实现，区分工具失败与队列故障。
5. 接入 QueueRuntime，按文末步骤手动验收。练习不要求添加测试文件、mock 或内联断言。

## 参考实现

### 1. `src/zeta/celery_app.py`

```python
import os

from celery import Celery

app = Celery(
    "zeta",
    broker=os.environ.get("ZETA_CELERY_BROKER_URL", "redis://127.0.0.1:6379/0"),
    backend=os.environ.get("ZETA_CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1"),
    include=["zeta.queue_tools"],
)

app.conf.update(
    task_default_queue="zeta.tools",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_accept_content=["json"],
    task_track_started=True,
    task_ignore_result=False,
    result_expires=3600,
    task_publish_retry=False,
    task_acks_late=False,
    worker_prefetch_multiplier=1,
    broker_connection_timeout=3,
    broker_transport_options={
        "socket_connect_timeout": 3,
        "socket_timeout": 3,
        "max_retries": 0,
    },
    redis_socket_connect_timeout=3,
    redis_socket_timeout=3,
    result_backend_always_retry=False,
    result_backend_transport_options={"retry_policy": {"max_retries": 0}},
)
```

这里使用默认的执行前确认，不启用任务自动重试。代价是 Worker 确认后崩溃，任务可能没有结果；主进程等待超时并保留 pending，不声称自动恢复。后续启用晚确认和重投时，再设计幂等和副作用核对。

`result_expires` 控制 Redis 结果的保留时间，不控制工具运行时长。网络连接参数用于约束常见故障等待，不是对所有底层系统调用的硬实时保证。

### 2. `src/zeta/queue_tools.py`

```python
import asyncio
import logging
import os
from pathlib import Path
from time import time
from typing import Any, Literal
from uuid import uuid4

from celery.exceptions import TimeoutError as CeleryTimeoutError
from langchain_core.messages import ToolCall
from pydantic import BaseModel, ConfigDict, Field

from zeta.celery_app import app
from zeta.tools import ToolError, resolve_tool_call

logger = logging.getLogger(__name__)
WAIT_SECONDS = 30.0


class ToolJob(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: Literal["read"]
    call_id: str = Field(min_length=1)
    args: dict[str, Any]
    workspace: str
    deadline: float = Field(allow_inf_nan=False)


class ToolReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: Literal["read"]
    call_id: str = Field(min_length=1)
    outcome: Literal["success", "failed"]
    content: str


def configured_workspace() -> Path:
    root = Path(os.environ["ZETA_QUEUE_WORKSPACE"]).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("queue workspace must be a directory")
    return root


@app.task(name="zeta.run_tool", max_retries=0)
def run_tool_job(payload: dict[str, Any]) -> dict[str, Any]:
    job = ToolJob.model_validate(payload)
    root = configured_workspace()
    if Path(job.workspace).resolve(strict=True) != root:
        raise ValueError("queue workspace mismatch")
    if time() >= job.deadline:
        raise TimeoutError("tool job expired before execution")

    call = ToolCall(name=job.name, args=job.args, id=job.call_id)
    try:
        handler, args = resolve_tool_call(call)
        content = handler(args, root)
    except ToolError as error:
        reply = ToolReply(
            name=job.name,
            call_id=job.call_id,
            outcome="failed",
            content=str(error),
        )
    else:
        reply = ToolReply(
            name=job.name,
            call_id=job.call_id,
            outcome="success",
            content=content,
        )
    return reply.model_dump(mode="json")


async def execute_queued(call: ToolCall, workspace: Path) -> str:
    root = workspace.resolve(strict=True)
    if root != configured_workspace():
        raise ValueError("queue workspace mismatch")
    if call["name"] != "read":
        raise ToolError("only read is enabled for queue execution")

    job = ToolJob(
        name="read",
        call_id=call["id"] or "",
        args=call["args"],
        workspace=str(root),
        deadline=time() + WAIT_SECONDS,
    )
    task_id = uuid4().hex
    logger.info("tool_call_id=%s celery_task_id=%s", job.call_id, task_id)

    def submit_and_wait() -> object:
        # 同步网络操作都在这个线程中；线程不触碰 Session 或 SQLite。
        result = app.send_task(
            "zeta.run_tool",
            kwargs={"payload": job.model_dump(mode="json")},
            task_id=task_id,
            queue="zeta.tools",
            retry=False,
            expires=WAIT_SECONDS,
        )
        remaining = job.deadline - time()
        if remaining <= 0:
            raise TimeoutError("tool job deadline elapsed during submission")
        try:
            return result.get(timeout=remaining, propagate=True)
        except CeleryTimeoutError as error:
            raise TimeoutError("tool job result timed out") from error

    async with asyncio.timeout(WAIT_SECONDS):
        payload = await asyncio.to_thread(submit_and_wait)
    reply = ToolReply.model_validate(payload)
    if (reply.name, reply.call_id) != (job.name, job.call_id):
        raise ValueError("tool reply identity mismatch")
    if reply.outcome == "failed":
        raise ToolError(reply.content)
    return reply.content
```

为什么只允许 `read`？当前真实注册工具只有它；用显式范围防止以后往 TOOLS 添加 write/bash 后，就自动获得队列重放或后台执行行为。增加其他工具时，需要同时评估权限、运行期限和副作用。

两种失败的处理不同：

- 文件不存在、参数错误等预期 `ToolError`：返回失败正文，主进程调度器构造错误 ToolMessage，让模型知道工具失败。
- Redis 连接故障、结果超时、Worker 异常、结果格式或身份不符：异常继续传播，结束本轮并保留 pending。不能把“没收到结果”当成“工具肯定没执行”。

`get(timeout=...)` 限制等待结果的时间；外层 asyncio timeout 限制当前协程的等待。协程取消后，已经开始的线程和 Worker 可能继续运行；后台线程只接触 Celery，不会自行把迟到结果写入 Session。已经取得的结果由 Celery get 消费，Redis 缓存依照结果过期配置清理；取消后遗留的结果同样等待过期。

`expires` 和 Worker 的 deadline 检查用于拒绝过期的排队任务，不会中断已经执行中的函数。第一版没有强制杀死运行中任务的能力。

### 3. 给 `src/zeta/dispatch.py` 增加一个可选执行入口

下面是相对 Day 2 实现的局部改动，不是另建一套调度器。`runner` 接收工具调用和工作区，异步返回正文；默认 None 仍使用原处理函数。

```diff
-from collections.abc import Sequence
+from collections.abc import Awaitable, Callable, Sequence

+type ToolRunner = Callable[[ToolCall, Path], Awaitable[str]]
+
 async def execute_tool(
     call: ToolCall,
     workspace: Path,
     hooks: Hooks,
     listeners: Sequence[Listener] = (),
+    *,
+    runner: ToolRunner | None = None,
 ) -> ToolExecution:
```

把类型别名放在所有 imports 之后。只替换原来调用 handler 的那一行，并保留外侧的 `try/except ToolError`：

```python
if runner is None:
    content = await asyncio.to_thread(handler, args, workspace)
else:
    validated_call = ToolCall(
        name=call["name"],
        args=args.model_dump(mode="json"),
        id=call["id"],
    )
    content = await runner(validated_call, workspace)
```

因此，主进程先做参数校验和 `before_tool`，拒绝时根本不入队。Worker 再次校验跨进程收到的数据，并执行已有 handler。`make_tool_message`、`after_tool` 和 raw/result 的处理仍在原位置。

### 4. `src/zeta/queue_runtime.py`

```python
from langchain_core.messages import ToolCall

from zeta.dispatch import execute_tool
from zeta.integration import ContextRuntime, Services
from zeta.loop import run_loop
from zeta.queue_tools import execute_queued
from zeta.runtime_base import ToolExecution


class QueueRuntime(ContextRuntime):
    async def execute(self, call: ToolCall) -> ToolExecution:
        return await execute_tool(
            call,
            self.workspace,
            self.hooks,
            self.listeners,
            runner=execute_queued,
        )


async def run_queued_session(
    session_id: str,
    prompt: str | None,
    services: Services,
) -> str:
    runtime = QueueRuntime(session_id, services)
    return await run_loop(prompt, runtime)
```

在你已有的 Day 7 调用入口中，将导入和调用 `run_session_task` 的位置换成 `run_queued_session`。仍使用原有的 `create_session`、Services 和数据库关闭流程；不用重新实现 Agent Loop，也不修改 Day 7 的入口函数。当前 CLI 是否已经连到 Day 7，要以你完成的练习为准，不能直接把 `uv run zeta` 当成本课已接通的入口。

## 手动运行与验收

以下步骤在把参考代码写入对应源码并安装依赖之后执行；仅创建本文档不会启动任何服务。

**终端一：启动本课使用的 Redis。** 仅在 6379 没有已有 Redis 时执行，不要覆盖其他应用的实例或配置。

```zsh
mkdir -p .local/zeta-redis
redis-server --bind 127.0.0.1 --port 6379 --appendonly yes --dir "$PWD/.local/zeta-redis"
```

这是前台进程。运行数据放在 `.local/zeta-redis`，应作为本地运行产物排除在 Git 之外；AOF 是 Redis 持久化配置，不代表本课具备 Session 自动恢复。

**终端二：从项目根目录启动 Worker。** 先设置前文的三个环境变量，再运行：

```zsh
uv run celery -A zeta.celery_app:app worker --loglevel=INFO --pool=solo --concurrency=1 -Q zeta.tools
```

macOS 本地第一版采用 solo，单个 Worker 顺序执行任务，方便理解进程边界。此模式不提供依赖 prefork 的软时间限制，也不会让多个工具同时运行。后续选用其他执行池时，需要重新验证对应的取消和超时行为。

**终端三：运行已接入 `run_queued_session` 的 Day 7 入口。** 使用相同环境变量和工作区，输入“请读取 README.md 并概括项目目标”。完成以下人工检查：

| 场景 | 应观察到什么 |
| --- | --- |
| 正常 read | Worker 收到 `zeta.run_tool`；主进程保存对应 ToolMessage，模型继续回答 |
| 读取不存在的文件 | Worker 返回工具失败正文；主进程保存错误 ToolMessage |
| before_tool 拒绝 | 主进程产生 denied 结果，Worker 没有收到对应任务 |
| Worker 未启动 | 任务可能已入 Redis；主进程约 30 秒后超时，Session 保留 pending |
| Redis 未启动 | 提交或取结果失败，本轮不宣称工具成功；保留不确定状态 |
| 主进程被取消 | 模型循环终止；不能据此声称 Worker 中的工具已经停止 |
| 尝试恢复含 pending 的 Session | 沿用 Day 3 的拒绝恢复行为，不自动再次提交工具 |

不要在真实模型偶然没有调用工具时把整条链路记为通过；必须观察到 Worker 任务和对应 ToolMessage。对“Worker 未启动”的场景，重启 Worker 后也需确认过期任务没有实际读取。

按项目已有命令检查实际实现：

```zsh
uv run --locked ruff format --check src/zeta/celery_app.py src/zeta/queue_tools.py src/zeta/queue_runtime.py src/zeta/dispatch.py
uv run --locked ruff check src/zeta/celery_app.py src/zeta/queue_tools.py src/zeta/queue_runtime.py src/zeta/dispatch.py
uv run --locked pyright --pythonpath .venv/bin/python
uv build
```

Celery 的动态 task 装饰器和第三方类型信息需要在实际安装版本下检查；不要为了消除提示全局关闭严格类型检查。静态检查通过也不能替代 Redis、Worker 和模型链路的实际运行。

## 本日交付边界

完成后可以说：Zeta 保留已有 Loop、Hooks 和 Session，通过 Redis 把只读工具交给独立 Celery Worker，并将结果按原调用 ID 回填。

本课没有实现同一批工具并发、自动重试、进程重启后的任务接回、恰好执行一次、运行中任务强制终止或跨机器文件同步。Redis 中有结果，也不等于 Session 已提交结果。

下一步确实需要重启恢复时，再持久化 `session_id / tool_call_id / celery_task_id` 的关联，并处理“任务已发出但映射尚未保存”“工具已执行但结果未提交”的中断窗口；不要靠简单重发来消除 pending。

## 官方资料

- [Celery 5.6 版本说明：Python 3.14 初步支持](https://docs.celeryq.dev/en/stable/changelog.html)
- [Redis Broker、结果 Backend 与可见性超时](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html)
- [任务提交、发送重试和过期时间](https://docs.celeryq.dev/en/stable/userguide/calling.html)
- [AsyncResult.get：等待超时与异常传播](https://docs.celeryq.dev/en/stable/reference/celery.result.html)
- [任务确认与幂等](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Worker 执行池及功能差异](https://docs.celeryq.dev/en/stable/userguide/concurrency/index.html)
