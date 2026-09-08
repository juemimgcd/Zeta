"""A fixed, workspace-scoped read tool."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.tools import ToolDefinition

# 读取文件的字节上限：32768 字节，不是 32768 个汉字。
MAX_READ_BYTES = 32_768


# 预期工具错误：参数、路径或读取失败；供外层转换或显示，不表示正常结果。
class ToolError(Exception):
    """An expected tool failure safe to return to the caller."""


# read 的参数模型，继承 Pydantic BaseModel 以获得运行时数据校验能力。
class ReadArgs(BaseModel):
    """Arguments accepted by the read tool."""

    # 拒绝额外参数，启用严格类型校验；模型提供的参数仍需经过本地验证。
    model_config = ConfigDict(extra="forbid", strict=True)
    # 要读取的路径字符串，至少一个字符；路径是否存在和越界由 read_file 检查。
    path: str = Field(min_length=1, description="UTF-8 file path inside the workspace")


# 输入已校验的 ReadArgs 和工作目录 Path，成功返回 UTF-8 文件正文字符串。
# 只允许目录范围内的小型普通文件；拒绝 .git/.env 等路径，失败抛 ToolError。
def read_file(args: ReadArgs, workspace: Path) -> str:
    """Read a small UTF-8 regular file inside the workspace."""
    try:
        # 解析实际根路径，strict=True 要求它存在。
        root = workspace.resolve(strict=True)
        # Path 的 / 运算符拼接路径；resolve 解析 .. 和符号链接后再判断是否越界。
        target = (root / args.path).resolve(strict=True)
        if not root.is_dir() or not target.is_relative_to(root):
            raise ToolError("path is outside the workspace")
        # 取得相对路径；这里 relative.parts 是路径组件元组，不是模型响应 parts。
        relative = target.relative_to(root)
        if any(
            p == ".git" or p == ".env" or p.startswith(".env.") for p in relative.parts
        ):
            raise ToolError("reading this path is denied")
        if not target.is_file():
            raise ToolError("read requires a regular file")
        # Trusted local workspace; use OS isolation for hostile concurrent changes.
        # 二进制模式读取，以字节检查大小；with 结束时关闭文件。
        # 此实现假设可信本地目录，不能防住恶意并发修改路径的所有情况。
        with target.open("rb") as file:
            # 多读取一个字节，用于区分“恰好达到上限”和“超过上限”。
            data = file.read(MAX_READ_BYTES + 1)
        if len(data) > MAX_READ_BYTES:
            raise ToolError("file exceeds the 32768-byte read limit")
        # 含零字节时按非文本拒绝；随后 decode 继续检查 UTF-8 编码是否合法。
        if b"\x00" in data:
            raise ToolError("read supports UTF-8 text only")
        return data.decode("utf-8")
    # 把底层解码错误转换为可读的工具错误；from None 隐去异常链显示。
    except UnicodeError:
        raise ToolError("read supports UTF-8 text only") from None
    except OSError, ValueError, RuntimeError:
        raise ToolError("cannot read the requested workspace file") from None


# 给模型看的工具说明表，键是工具名称；它不自动调用本地 read_file。
TOOL_DEFINITIONS = {
    "read": ToolDefinition(
        name="read",
        description="Read a UTF-8 workspace file of at most 32768 bytes.",
        # 由参数模型生成 JSON Schema，描述 path 的类型、必填和额外字段规则。
        parameters_json_schema=ReadArgs.model_json_schema(),
        # 服务商工具 schema 的严格模式开关，与本地 ReadArgs.strict 是不同层。
        strict=False,
    )
}


# 接收模型给出的 ToolCallPart，校验名称/参数并执行 read，返回 ToolReturnPart。
# Day 1 遇到预期失败会抛 ToolError 停止；这里尚不包装 failed 结果继续运行。
def execute_tool(call: ToolCallPart, workspace: Path) -> ToolReturnPart:
    """Dispatch the fixed read tool; the Day 1 baseline stops on expected tool failure."""
    # tool_name 是要调用哪个工具；只接受固定定义表中的名称。
    if call.tool_name not in TOOL_DEFINITIONS:
        raise ToolError("unknown tool")
    try:
        # call.args 可以是 JSON 字符串或字典：分别选择 JSON 解析校验和对象校验。
        # 成功后得到 ReadArgs 实例，使用 args.path 读取路径字段。
        args = (
            ReadArgs.model_validate_json(call.args)
            if isinstance(call.args, str)
            else ReadArgs.model_validate(call.args)
        )
    except ValidationError:
        raise ToolError("read expects an object with a string path only") from None
    # 先执行 read_file 得到正文，再包装为工具结果对象；此处尚未发回模型。
    return ToolReturnPart(
        # 沿用调用中的工具名称，例如 read。
        tool_name=call.tool_name,
        # 沿用这一次调用的编号，不能另造 ID；模型靠它识别结果对应哪个调用。
        tool_call_id=call.tool_call_id,
        # content 保存实际读取正文，不是模型猜测的文件内容。
        content=read_file(args, workspace),
    )
