"""Read tool: metadata, arguments, and file-reading implementation."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from zeta.builtin_tools import ToolError

MAX_READ_BYTES = 32_768


class ReadArgs(BaseModel):
    """Arguments accepted by the read tool."""

    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, description="UTF-8 file path inside the workspace")


def read_file(args: ReadArgs, workspace: Path) -> str:
    """Read a UTF-8 workspace file of at most 32768 bytes."""
    try:
        root = workspace.resolve(strict=True)
        # 解析 .. 和符号链接后再检查工作区边界。
        target = (root / args.path).resolve(strict=True)
        if not root.is_dir() or not target.is_relative_to(root):
            raise ToolError("path is outside the workspace")
        relative = target.relative_to(root)
        if any(
            p == ".git" or p == ".env" or p.startswith(".env.") for p in relative.parts
        ):
            raise ToolError("reading this path is denied")
        if not target.is_file():
            raise ToolError("read requires a regular file")
        # 假设可信本地目录；恶意并发修改路径需要 OS 隔离。
        with target.open("rb") as file:
            # 多读一个字节以判断是否超限。
            data = file.read(MAX_READ_BYTES + 1)
        if len(data) > MAX_READ_BYTES:
            raise ToolError("file exceeds the 32768-byte read limit")
        if b"\x00" in data:
            raise ToolError("read supports UTF-8 text only")
        return data.decode("utf-8")
    except UnicodeError:
        raise ToolError("read supports UTF-8 text only") from None
    except OSError, ValueError, RuntimeError:
        raise ToolError("cannot read the requested workspace file") from None
