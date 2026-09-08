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

# 命令行入口：读取用户参数，加载配置，运行异步 Agent 并显示结果。
# 失败时转换为退出码和简短错误信息；本函数不返回模型响应对象。
def main() -> None:
    # 命令行参数解析器；程序名 zeta 用于帮助和错误提示。
    parser = argparse.ArgumentParser(prog="zeta")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("-p", "--prompt", required=True)
    # 解析 --prompt/-p 等输入，得到保存参数值的命名空间对象。
    args = parser.parse_args()
    # prompt 是用户输入字符串；cast 提供类型提示，不执行值转换。
    prompt = cast(str, args.prompt)
    # 从本地 .env 加载配置，但不覆盖进程中已有环境变量。
    load_dotenv(override=False)
    try:
        # 同步 main 通过 asyncio.run 进入事件循环，等待最终文字回答。
        # Path.cwd() 将当前工作目录作为工具访问范围。
        output = asyncio.run(run_agent(prompt, Path.cwd()))
    # 参数/配置类问题使用退出码 2；运行失败通常用 1；取消用 130。
    except ValueError:
        parser.exit(2, "zeta: invalid input or run configuration\n")
    except UserError:
        parser.exit(2, "zeta: check DEEPSEEK_API_KEY and model configuration\n")
    # HTTP 错误是较具体的异常，先于更宽泛的 ModelAPIError 捕获。
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
    # 只有正常取得回答才输出到标准输出；错误分支通过 parser.exit 结束进程。
    print(output)