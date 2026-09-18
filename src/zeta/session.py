import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from pydantic import BaseModel, Field, TypeAdapter

from zeta.storage import JsonStore


class Entry(BaseModel):
    # 消息记录的唯一标识，用于追溯记忆来源等场景。
    id: str = Field(default_factory=lambda: uuid4().hex)
    # 最终写入会话历史的单条消息，保存为带格式标记的 JSON 字符串。
    message_json: str
    # 工具的原始返回消息 JSON；未提供原始消息时保存最终工具消息，非工具记录默认为空。
    raw_json: str | None = None
    # 这条记录的创建时间，使用 UTC 时区的 ISO 8601 字符串。
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class SessionData(BaseModel):
    # 会话的唯一标识，也是持久化保存和读取会话时使用的键。
    id: str
    # 会话所属的访问范围，由运行时检查是否属于允许访问的范围。
    scope: str
    # 按写入顺序保存的消息记录，可还原为模型使用的历史消息。
    entries: list[Entry] = Field(default_factory=list[Entry])
    # 尚未提交结果的工具调用：调用 ID → 工具名称；不代表工具尚未执行。
    pending: dict[str, str] = Field(default_factory=dict)
    # 当前状态：就绪、运行中、已完成、已停止、失败或已取消。
    status: Literal[
        "ready", "running", "completed", "stopped", "failed", "cancelled"
    ] = "ready"
    # 结束或中止本轮运行的原因说明；新一轮开始时清空。
    reason: str = ""
    # 预留的关联记忆 ID 列表；当前代码尚未写入或读取该字段。
    memory_ids: list[str] = Field(default_factory=list[str])


def encode(messages: Sequence[BaseMessage]) -> str:
    return json.dumps(
        {"format": "langchain-messages-v1", "messages": messages_to_dict(messages)},
        ensure_ascii=False,
    )


def decode(entry: Entry) -> BaseMessage:
    payload = TypeAdapter(dict[str, Any]).validate_json(entry.message_json)
    if payload.get("format") != "langchain-messages-v1":
        raise ValueError(
            "unsupported message format; old sessions need explicit migration"
        )
    data = TypeAdapter(list[dict[str, Any]]).validate_python(payload["messages"])
    messages = messages_from_dict(data)
    if len(messages) != 1:
        raise ValueError("an entry must contain exactly one message")
    return messages[0]


def load_session(store: JsonStore, session_id: str) -> SessionData:
    body = store.get("session", session_id)
    if body is None:
        raise KeyError("unknown session")
    return SessionData.model_validate_json(body)


def save_session(store: JsonStore, session: SessionData) -> None:
    store.put("session", session.id, session.model_dump_json())


def create_session(store: JsonStore, scope: str) -> str:
    if not scope.strip():
        raise ValueError("scope is required")
    session = SessionData(id=uuid4().hex, scope=scope)
    with store.transaction():
        save_session(store, session)
    return session.id


def append_user(store: JsonStore, session_id: str, prompt: str) -> str:
    if not prompt.strip():
        raise ValueError("empty prompt")
    with store.transaction():
        session = load_session(store, session_id)
        if session.pending or session.status not in ("ready", "completed"):
            raise ValueError("finish the existing run or create a new session first")
        if session.entries:
            last = decode(session.entries[-1])
            if not isinstance(last, AIMessage) or last.tool_calls:
                raise ValueError("previous task has no final response")
        entry = Entry(message_json=encode([HumanMessage(content=prompt)]))
        session.entries.append(entry)
        session.status, session.reason = ("running", "")
        save_session(store, session)
    return entry.id


def commit_response(store: JsonStore, session_id: str, response: AIMessage) -> str:
    """Persist a response already validated by the loop; enforce session state."""
    calls = response.tool_calls
    with store.transaction():
        session = load_session(store, session_id)
        if session.pending or session.status != "running":
            raise ValueError("session is not ready for a response")
        if not session.entries or not isinstance(
            decode(session.entries[-1]), (HumanMessage, ToolMessage)
        ):
            raise ValueError("response must follow user input or a tool-result batch")
        entry = Entry(message_json=encode([response]))
        session.entries.append(entry)
        session.pending = {(call["id"] or ""): call["name"] for call in calls}
        save_session(store, session)
    return entry.id


def commit_tool_result(
    store: JsonStore,
    session_id: str,
    result: ToolMessage,
    raw: ToolMessage | None = None,
) -> str:
    """Persist results already checked by after_tool; enforce pending state."""
    original = result if raw is None else raw
    with store.transaction():
        session = load_session(store, session_id)
        if session.pending.get(result.tool_call_id) != result.name:
            raise ValueError("unknown or already committed tool result")
        entry = Entry(
            message_json=encode([result]),
            raw_json=encode([original]),
        )
        session.entries.append(entry)
        del session.pending[result.tool_call_id]
        save_session(store, session)
    return entry.id


def finish_session(
    store: JsonStore,
    session_id: str,
    status: Literal["completed", "stopped", "failed", "cancelled"],
    reason: str = "",
) -> None:
    with store.transaction():
        session = load_session(store, session_id)
        if status == "completed" and session.pending:
            raise ValueError("cannot complete a pending batch")
        session.status, session.reason = (status, reason)
        save_session(store, session)


def history_messages(entries: Sequence[Entry]) -> list[BaseMessage]:
    """Decode in order; the loop validates the prepared history before requesting."""
    return [decode(entry) for entry in entries]
