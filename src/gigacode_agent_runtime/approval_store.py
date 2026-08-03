"""Persist explicit approvals without prompt or environment data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .errors import AgentRuntimeError, ErrorCode
from .locking import FileLock
from .serialization import atomic_write_json
from .state_store_types import utc_timestamp


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    run_id: str
    plan_hash: str
    gate: str
    approved_at: str


class ApprovalStore:
    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "approvals.json"
        self._lock_path = run_dir / "approvals.lock"

    def _load_unlocked(self) -> tuple[ApprovalRecord, ...]:
        if not self._path.exists():
            return ()
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
            records = cast(list[dict[str, Any]], parsed["approvals"])
            return tuple(
                ApprovalRecord(
                    run_id=str(record["run_id"]),
                    plan_hash=str(record["plan_hash"]),
                    gate=str(record["gate"]),
                    approved_at=str(record["approved_at"]),
                )
                for record in records
            )
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AgentRuntimeError(
                ErrorCode.STATE_CORRUPTED,
                f"Approval store is corrupted: {self._path}",
                details={"path": str(self._path)},
            ) from exc

    def approve(self, run_id: str, plan_hash: str, gate: str) -> ApprovalRecord:
        with FileLock(self._lock_path, blocking=True):
            records = list(self._load_unlocked())
            existing = next(
                (
                    record
                    for record in records
                    if record.run_id == run_id
                    and record.plan_hash == plan_hash
                    and record.gate == gate
                ),
                None,
            )
            if existing is not None:
                return existing
            record = ApprovalRecord(
                run_id=run_id,
                plan_hash=plan_hash,
                gate=gate,
                approved_at=utc_timestamp(),
            )
            records.append(record)
            atomic_write_json(
                self._path,
                {
                    "approvals": [
                        {
                            "run_id": item.run_id,
                            "plan_hash": item.plan_hash,
                            "gate": item.gate,
                            "approved_at": item.approved_at,
                        }
                        for item in records
                    ]
                },
            )
            return record

    def is_approved(self, run_id: str, plan_hash: str, gate: str) -> bool:
        with FileLock(self._lock_path, blocking=True):
            return any(
                record.run_id == run_id
                and record.plan_hash == plan_hash
                and record.gate == gate
                for record in self._load_unlocked()
            )
