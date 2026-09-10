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