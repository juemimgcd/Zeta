# 配套基础代码：直接使用，不作为手写练习

这份文档集中放接入代码。model_io.py 已提供在 src/zeta 中，无需再复制。下面保留它的完整内容供查阅；cli.py 是 Day 1 的接入版本，仍需等 run_agent 完成后再替换当前单次流式入口。

## 你只需要认识的模型契约

`request_once(model, history)` 返回完整 ModelResponse，可能包含文本和 ToolCallPart；不执行工具、不继续下一轮、不裁剪历史。
ToolReturnPart 必须带原调用的 tool_name 和 tool_call_id。框架消息类型可以直接使用，无需先手写 DTO、Provider 或 HTTP/SSE 层。

模型协议入口已按本地安装包的 direct.py 和 models/__init__.py 核对。API 错误向外抛出；完成原因由你在 Loop 中判断。

## 已提供：src/zeta/model_io.py

```python
from collections.abc import Sequence

from pydantic_ai.direct import model_request
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel

from zeta.tools import TOOL_DEFINITIONS


def create_model() -> OpenAIChatModel:
    return OpenAIChatModel("deepseek-chat", provider="deepseek")


async def request_once(
    model: OpenAIChatModel, history: Sequence[ModelMessage]
) -> ModelResponse:
    return await model_request(
        model,
        history,
        model_settings={"timeout": 60.0},
        model_request_parameters=ModelRequestParameters(
            function_tools=list(TOOL_DEFINITIONS.values())
        ),
    )
```

一个 run 内用 `async with create_model() as model` 管理连接生命周期，再按需要多次调用 request_once。连接怎么创建直接照用；调用几次、传什么 history 由你决定。

## 直接提供：src/zeta/cli.py

契约：Day 1–2 的 app.py 提供 `async run_agent(prompt: str, workspace: Path) -> str` 和 `RunLimitError`。后续 Session 等依赖通过 app.py 组装；不要求每日重写 CLI。

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
from zeta.app import RunLimitError, run_agent
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

`--help` / `--version` 在加载 .env 和建立连接之前退出。事件 JSON 和流式终端输出留到选修，不影响核心主线。

## 直接复用的现有实现

- `src/zeta/tools.py` 的 ReadArgs、read_file、TOOL_DEFINITIONS：保留现有工作区路径、敏感路径、UTF-8 和 32768 字节限制。Day 1 暂用现有 execute_tool，Day 2 再手写调度策略。
- `src/zeta/app.py` 的旧 run_prompt / stream_prompt：作为单次接入参考；不用重复抄写。新的 request_once 保留完整响应，旧文本返回值不适合作为工具 Loop 输入。
- `pyproject.toml` 已有 PydanticAI、Pydantic、dotenv 依赖和 zeta 入口，不重复安装或新增框架。

后续 SQLite 连接、建表、CRUD 与消息序列化属于配套工程，进入 Day 3/4 时再补齐，不让你为练习核心策略先写数据库封装。它们当前尚未交付；每日提及的 store 是待提供的契约，不是现有可导入模块。

## 完成源码练习后的检查

在项目根目录运行：

```zsh
uv run ruff format --check src/zeta
uv run ruff check src/zeta
uv run pyright --pythonpath .venv/bin/python
uv build
uv run zeta --help
uv run zeta --version
```

真实模型闭环另用当天的手动任务验证。未完成 run_agent 时不要切换上述 CLI 并宣称接入成功。已有源码检查失败需要区分原有问题和当天修改，不为了文档更新修其他文件。
