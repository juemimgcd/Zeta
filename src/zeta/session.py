import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolCall,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from pydantic import BaseModel, Field, TypeAdapter

from zeta.loop_common import response_calls, validate_history
from zeta.storage import JsonStore


class Entry(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    message_json: str
    raw_json: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class SessionData(BaseModel):
    id: str
    scope: str
    entries: list[Entry] = Field(default_factory=list[Entry])
    pending: dict[str, str] = Field(default_factory=dict)
    status: Literal[
        "ready", "running", "completed", "stopped", "failed", "cancelled"
    ] = "ready"
    reason: str = ""
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
        if session.pending or session.status == "running":
            raise ValueError("finish or explicitly resolve the existing run first")
        if session.entries:
            last = decode(session.entries[-1])
            if not isinstance(last, AIMessage) or response_calls(last):
                raise ValueError("previous task has no final response")
        entry = Entry(message_json=encode([HumanMessage(content=prompt)]))
        session.entries.append(entry)
        session.status, session.reason = ("running", "")
        save_session(store, session)
    return entry.id


def commit_response(store: JsonStore, session_id: str, response: AIMessage) -> str:
    calls = response_calls(response)
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
    original = result if raw is None else raw
    if (result.name, result.tool_call_id, result.status, result.artifact) != (
            original.name,
            original.tool_call_id,
            original.status,
            original.artifact,
    ):
        raise ValueError("raw and final result disagree")
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
    """ToolMessage is already a complete message; retain order and validate pairs."""
    messages = [decode(entry) for entry in entries]
    validate_history(messages)
    return messages


class ResumePoint(BaseModel):
    session: SessionData
    action: Literal["new_input", "continue", "resolve_pending", "review"]


def load_resume_point(store: JsonStore, session_id: str) -> ResumePoint:
    session = load_session(store, session_id)
    if session.pending:
        action = "resolve_pending"
    elif not session.entries:
        action = "new_input"
    elif session.status in ("failed", "cancelled", "stopped"):
        action = "review"
    else:
        history_messages(session.entries)
        last = decode(session.entries[-1])
        action = (
            "review"
            if isinstance(last, AIMessage) and session.status == "running"
            else "new_input"
            if isinstance(last, AIMessage)
            else "continue"
        )
    return ResumePoint(session=session, action=action)


def pending_calls(session: SessionData) -> list[ToolCall]:
    for entry in reversed(session.entries):
        message = decode(entry)
        if isinstance(message, AIMessage):
            return [
                call
                for call in response_calls(message)
                if (call["id"] or "") in session.pending
            ]
    return []