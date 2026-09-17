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
        raise ValueError
    data = TypeAdapter(list[dict[str, Any]]).validate_python(payload["messages"])
    messages = messages_from_dict(data)
    if len(messages) != 1:
        raise ValueError
    return messages[0]


def load_session(store: JsonStore, session_id: str) -> SessionData:
    body = store.get("session", session_id)
    if not body:
        raise ValueError
    return SessionData.model_validate_json(body)


def save_session(store: JsonStore, session: SessionData) -> None:
    store.put("session", session.id, session.model_dump_json())


def create_session(store: JsonStore, scope: str) -> str:
    if not scope.strip():
        raise ValueError
    session = SessionData(
        id=uuid4().hex,
        scope=scope,
    )
    save_session(store, session)
    return session.id



def append_user(store: JsonStore, session_id: str, prompt: str) -> str:
    if not prompt.strip():
        raise ValueError
    with store.transaction():
        session = load_session(store, session_id)
        if session.pending or session.status not in ("completed","ready"):
            raise ValueError
        if session.entries:
            last = decode(session.entries[-1])
            if not isinstance(last,AIMessage) or last.tool_calls:
                raise ValueError
        entry = Entry(
            message_json=encode([HumanMessage(content=prompt)])
        )
        session.entries.append(entry)
        session.status,session.reason = "running",""
        save_session(store, session)
    return session.id




def commit_response(store: JsonStore, session_id: str, response: AIMessage) -> str:
    calls = response.tool_calls
    with store.transaction():
        session = load_session(store, session_id)
        if session.pending or session.status != "running":
            raise ValueError
        if session.entries:
            last = decode(session.entries[-1])
            if not isinstance(last,(HumanMessage,ToolMessage)):
                raise ValueError
        entry = Entry(
            message_json=encode([response])
        )
        session.entries.append(entry)
        session.pending = {(call["id"] or ""):call["name"] for call in calls}
        save_session(store, session)
    return session.id



def commit_tool_result(
        store: JsonStore,
        session_id: str,
        result: ToolMessage,
        raw: ToolMessage | None = None,
) -> str:
    original = result if raw is None else raw
    with store.transaction():
        session = load_session(store, session_id)
        if session.pending.get(result.tool_call_id)!=result.name:
            raise ValueError
        entry = Entry(
            message_json=encode([result]),
            raw_json=encode([original]),
        )
        session.entries.append(entry)
        del session.pending[result.tool_call_id]
        save_session(store, session)
    return session.id


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
