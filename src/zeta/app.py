from pathlib import Path

from zeta.loop import run_loop
from zeta.runtime_base import Runtime


# 固定应用入口：prompt 为用户输入，workspace 为工具工作目录。
# runtime 可传入已有运行对象；省略时创建基础 Runtime。
# 异步返回最终回答字符串；请求、工具及运行错误继续向外传播。
async def run_agent(
        prompt: str, workspace: Path, *, runtime: Runtime | None = None
) -> str:
    """Stable, supplied entry point. The user's implementation lives in loop.py."""
    # 条件表达式：传了 runtime 就使用它，否则创建默认对象。
    active = runtime if runtime is not None else Runtime(workspace)
    # 确认入口指定目录与运行对象的实际目录一致，避免使用错误的工具作用域。
    if active.workspace != workspace.resolve(strict=True):
        raise ValueError("runtime workspace mismatch")
    # 进入唯一的 Agent 循环；后续更换 Runtime 行为也复用这个入口。
    return await run_loop(prompt, active)