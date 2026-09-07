import json
from dataclasses import dataclass
from typing import Literal

type EventType = Literal[
    "run_start",
    "text_delta",
    "usage",
    "run_end",
    "error",
]
type EventValue = str | int


@dataclass(frozen=True, slots=True)
class ZetaEvent:
    type: EventType
    data: dict[str, EventValue]


def event_to_json(event: ZetaEvent) -> str:
    """Encode one event as compact JSON while preserving Chinese text."""
    return json.dumps(
        {**event.data, "type": event.type},
        ensure_ascii=False,
        separators=(",", ":"),
    )
