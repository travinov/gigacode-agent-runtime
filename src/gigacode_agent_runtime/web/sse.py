"""Server-Sent Events cursor helpers."""

from __future__ import annotations

import json

from ..domain import RunEvent
from ..event_log import event_to_document


def encode_event(event: RunEvent) -> str:
    data = json.dumps(
        event_to_document(event),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {event.event_id}\nevent: runtime\ndata: {data}\n\n"


def encode_heartbeat(cursor: int) -> str:
    return f"event: heartbeat\ndata: {{\"cursor\":{cursor}}}\n\n"


def parse_cursor(last_event_id: str | None, query_cursor: str | None) -> int:
    raw = last_event_id or query_cursor or "0"
    try:
        value = int(raw)
    except ValueError:
        return 0
    return max(0, value)
