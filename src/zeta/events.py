import json
from dataclasses import dataclass
from typing import Literal

# 事件名的类型别名：运行开始、文字增量、用量、结束、错误。
type EventType = Literal[
    "run_start",
    "text_delta",
    "usage",
    "run_end",
    "error",
]
# 事件数据值只约定为字符串或整数；类型别名自身不执行运行时校验。
type EventValue = str | int


@dataclass(frozen=True, slots=True)
# 一条本地结构化事件；dataclass 生成初始化，slots 限制随意增加实例属性。
# frozen 限制字段重新赋值，但 data 字典本身并未因此递归冻结。
class ZetaEvent:
    # 事件种类，只允许 EventType 中声明的名字。
    type: EventType
    # 事件携带的信息，例如文字片段或 token 数；这是本地事件，不是模型消息。
    data: dict[str, EventValue]


# 将一条 ZetaEvent 编码为紧凑 JSON 字符串；不打印、不写文件，也不自动换行。
# 同名 type 键以 event.type 为准；ensure_ascii=False 直接保留中文字符。
def event_to_json(event: ZetaEvent) -> str:
    """Encode one event as compact JSON while preserving Chinese text."""
    return json.dumps(
        {**event.data, "type": event.type},
        ensure_ascii=False,
        separators=(",", ":"),
    )
