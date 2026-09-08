# 固定基础代码：一次准备，八天复用

不熟悉下文的类、函数和属性时，先读 [Day 1 前置知识](prerequisites.md)，再回来准备基础文件。

本路线从 Day 1 起固定入口、运行配置和接入契约。下面文件直接提供，不作为手写练习；后续单元不再给它们的另一版。已有 src 文件保留，本次文档更新不会写入或覆盖你的业务源码。

## 文件所有权

| 归属 | 文件 | 后续如何使用 |
| --- | --- | --- |
| 本配套文档 | app.py、runtime_base.py、model_io.py、cli.py、storage.py | 一次准备，之后保持不变 |
| Day 1 | loop_common.py、loop.py | 唯一协议检查与唯一 run_loop，全部后续单元复用 |
| Day 2 | hooks.py、lifecycle.py、dispatch.py、hook_runtime.py | 新增 Hook/事件/调度，无需改 Day 1 |
| Day 3 | session.py、session_runtime.py | 新增提交/恢复，无需改 Day 1/2 |
| Day 4 | memory.py | 独立记忆策略 |
| Day 5 | context.py | 独立上下文选择 |
| Day 6 | compaction.py | 独立摘要策略 |
| Day 7 | integration.py | 组装前面能力，调用既有 run_loop |
| Day 8 | team_budget.py、orchestration.py | Worker 复用 Day 7，不修改父级接口 |

现有 tools.py 的 ReadArgs、read_file、固定工具定义和基础同步 execute_tool 直接复用。Day 2 的异步调度放在新文件 dispatch.py，不覆盖基础工具实现。包的 __init__.py 及依赖沿用当前项目。

## 固定入口怎么扩展

`app.run_agent(prompt, workspace, *, runtime=None)` 是直接提供的稳定入口；实际循环只有 Day 1 的 `loop.run_loop`。默认 Runtime 真实执行单次模型调用和 read，并保存内存历史；不是 mock，也不把未来未实现的能力标为成功。

Runtime 的接入点从一开始就齐全：start、begin_turn、prepare、on_response、execute、on_result、after_turn、retry、finish。后续新类只增加自己的处理，并调用已有方法；它们不修改基类、不复制循环。

- Day 1：默认 Runtime，学习循环和配对。
- Day 2：传 HookRuntime，仍调用同一个 run_agent。
- Day 3：新 SessionRuntime 持久化；用同一个 run_loop 接受新输入或恢复。
- Day 7：ContextRuntime 只组装上下文和重试策略，run_session_task 是调用 run_loop 的薄入口。
- Day 8：为 Services 传共享 request/summarizer，Worker 仍调用 Day 7 入口。

`RunOptions` 的次数/时限/输出上限，`ModelIO` 的模型请求/摘要函数，`ToolExecution` 的原始与最终结果都预先定义。运行配置不随天数换签名，错误类型在 Day 1 骨架提前提供。

## 一次提供的完整文件

先将下面基础文件与 Day 1 骨架组合。app.py 导入你要完成的 loop.py，runtime_base.py 导入 Day 1 已提供定义的 loop_common.py；不存在对尚未新增的 Day 2–8 模块的导入。

## 直接提供：src/zeta/runtime_base.py

```python
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


class RequestFn(Protocol):
    def __call__(
        self,
        model: OpenAIChatModel,
        messages: Sequence[ModelMessage],
        /,
        *,
        max_tokens: int,
    ) -> Awaitable[ModelResponse]: ...


type SummaryFn = Callable[[str], Awaitable[str]]
type RunStatus = Literal["completed", "stopped", "failed", "cancelled"]


@dataclass(frozen=True)
class ModelIO:
    request: RequestFn = request_once
    summarize: SummaryFn = summarize_once
    factory: Callable[[], OpenAIChatModel] = create_model


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
    raw: ToolReturnPart
    result: ToolReturnPart


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
        self.history: list[ModelMessage] = []
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
        self.history.append(
            ModelRequest.user_text_prompt(prompt, instructions=INSTRUCTIONS)
        )

    async def begin_turn(self) -> None:
        """Baseline has no event subscribers."""

    async def prepare(self) -> list[ModelMessage]:
        return deepcopy(self.history)

    async def on_response(self, response: ModelResponse) -> None:
        self.history.append(response)

    async def execute(self, call: ToolCallPart) -> ToolExecution:
        result = execute_tool(call, self.workspace)
        return ToolExecution(deepcopy(result), result)

    async def on_result(self, execution: ToolExecution) -> None:
        self.executions.append(execution)

    async def after_turn(self, results: list[ToolReturnPart]) -> None:
        if results:
            self.history.append(ModelRequest(parts=results, instructions=INSTRUCTIONS))

    async def retry(self, error: ModelHTTPError) -> bool:
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
from collections.abc import Sequence

from pydantic_ai.direct import model_request
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel

from zeta.tools import TOOL_DEFINITIONS


def create_model() -> OpenAIChatModel:
    return OpenAIChatModel("deepseek-chat", provider="deepseek")


async def request_once(
    model: OpenAIChatModel,
    history: Sequence[ModelMessage],
    *,
    max_tokens: int = 2048,
) -> ModelResponse:
    return await model_request(
        model,
        history,
        model_settings={"timeout": 60.0, "max_tokens": max_tokens},
        model_request_parameters=ModelRequestParameters(
            function_tools=list(TOOL_DEFINITIONS.values())
        ),
    )


async def summarize_once(prompt: str) -> str:
    async with create_model() as model:
        response = await model_request(
            model,
            [ModelRequest.user_text_prompt(prompt)],
            model_settings={"timeout": 60.0, "max_tokens": 2048},
            model_request_parameters=ModelRequestParameters(function_tools=[]),
        )
    if (
        response.state != "complete"
        or response.finish_reason != "stop"
        or not (response.text or "").strip()
    ):
        raise ValueError("incomplete summary response")
    return response.text or ""
```

## 直接提供：src/zeta/cli.py

```python
import argparse
import asyncio
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UserError,
)

from zeta import __version__
from zeta.app import run_agent
from zeta.loop_common import RunLimitError
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
        parser.exit(2, "zeta: invalid input or run configuration\n")
    except UserError:
        parser.exit(2, "zeta: check DEEPSEEK_API_KEY and model configuration\n")
    except ModelHTTPError as error:
        parser.exit(1, f"zeta: model request failed: HTTP {error.status_code}\n")
    except ModelAPIError:
        parser.exit(1, "zeta: model request failed\n")
    except UnexpectedModelBehavior:
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
