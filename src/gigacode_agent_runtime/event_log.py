"""Append-only JSONL event log with stable cursors."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from .domain import RunEvent
from .errors import AgentRuntimeError, ErrorCode
from .hashing import canonical_json
from .locking import FileLock
from .schema_registry import validate_document
from .state_store_types import utc_timestamp
from .version import RUN_EVENT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class EventPage:
    events: tuple[RunEvent, ...]
    next_cursor: int
    has_more: bool


def _event_to_document(event: RunEvent) -> dict[str, object]:
    return {
        "schema_version": event.schema_version,
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "run_id": event.run_id,
        "type": event.type,
        "step_instance_id": event.step_instance_id,
        "payload": dict(event.payload),
    }


def _event_from_document(document: Mapping[str, Any]) -> RunEvent:
    payload = cast(Mapping[str, object], document["payload"])
    step_instance_id = document.get("step_instance_id")
    return RunEvent(
        schema_version=str(document["schema_version"]),
        event_id=int(document["event_id"]),
        timestamp=str(document["timestamp"]),
        run_id=str(document["run_id"]),
        type=str(document["type"]),
        step_instance_id=str(step_instance_id) if step_instance_id is not None else None,
        payload=MappingProxyType(dict(payload)),
    )


class EventLog:
    def __init__(self, run_dir: Path, *, run_id: str = "run_test") -> None:
        self._run_id = run_id
        self._path = run_dir / "events.jsonl"
        self._lock_path = run_dir / "events.lock"

    def _load_unlocked(self) -> list[RunEvent]:
        if not self._path.exists():
            return []
        events: list[RunEvent] = []
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
            for _line_number, line in enumerate(lines, start=1):
                if not line:
                    continue
                parsed = json.loads(line)
                validate_document("run-event-v1", parsed)
                events.append(_event_from_document(cast(Mapping[str, Any], parsed)))
        except (OSError, UnicodeError, json.JSONDecodeError, AgentRuntimeError) as exc:
            raise AgentRuntimeError(
                ErrorCode.STATE_CORRUPTED,
                f"Event log is corrupted: {self._path}",
                details={"path": str(self._path), "line": locals().get("_line_number")},
            ) from exc
        return events

    def append(
        self,
        event_type: str,
        payload: Mapping[str, object],
        *,
        step_instance_id: str | None = None,
    ) -> RunEvent:
        with FileLock(self._lock_path, blocking=True):
            events = self._load_unlocked()
            event = RunEvent(
                schema_version=RUN_EVENT_SCHEMA_VERSION,
                event_id=events[-1].event_id + 1 if events else 1,
                timestamp=utc_timestamp(),
                run_id=self._run_id,
                type=event_type,
                step_instance_id=step_instance_id,
                payload=MappingProxyType(dict(payload)),
            )
            document = _event_to_document(event)
            validate_document("run-event-v1", document)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(canonical_json(document))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            return event

    def read(self, *, after: int = 0, limit: int = 100) -> EventPage:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with FileLock(self._lock_path, blocking=True):
            events = [event for event in self._load_unlocked() if event.event_id > after]
        selected = tuple(events[:limit])
        next_cursor = selected[-1].event_id if selected else after
        return EventPage(
            events=selected,
            next_cursor=next_cursor,
            has_more=len(events) > len(selected),
        )
