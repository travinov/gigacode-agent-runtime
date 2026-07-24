"""Durable idempotency records for run creation."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from .errors import AgentRuntimeError, ErrorCode
from .locking import FileLock
from .serialization import atomic_write_json

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


class IdempotencyStore:
    """Map a caller-owned key and request signature to one durable run ID."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir.resolve(strict=False)
        self._path = self._data_dir / "idempotency.json"
        self._lock_path = self._data_dir / "idempotency.lock"

    @staticmethod
    def _validate_key(key: str) -> None:
        if not _KEY_PATTERN.fullmatch(key):
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                "Idempotency key must contain 1-200 safe ASCII characters",
                details={"idempotency_key": key},
            )

    def _read_unlocked(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AgentRuntimeError(
                ErrorCode.STATE_CORRUPTED,
                "Idempotency store is corrupted",
                details={"path": str(self._path)},
            ) from exc
        if not isinstance(parsed, dict):
            raise AgentRuntimeError(
                ErrorCode.STATE_CORRUPTED,
                "Idempotency store must be a JSON object",
                details={"path": str(self._path)},
            )

        records: dict[str, dict[str, str]] = {}
        for raw_key, raw_record in cast(Mapping[str, Any], parsed).items():
            if (
                not isinstance(raw_key, str)
                or not isinstance(raw_record, Mapping)
                or not isinstance(raw_record.get("signature"), str)
                or not isinstance(raw_record.get("run_id"), str)
            ):
                raise AgentRuntimeError(
                    ErrorCode.STATE_CORRUPTED,
                    "Idempotency store contains an invalid record",
                    details={"path": str(self._path)},
                )
            records[raw_key] = {
                "signature": str(raw_record["signature"]),
                "run_id": str(raw_record["run_id"]),
            }
        return records

    def get_or_create(
        self,
        key: str,
        signature: str,
        create: Callable[[], str],
    ) -> str:
        self._validate_key(key)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        with FileLock(self._lock_path, blocking=True):
            records = self._read_unlocked()
            existing = records.get(key)
            if existing is not None:
                if existing["signature"] != signature:
                    raise AgentRuntimeError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "Idempotency key was already used for a different request",
                        details={"idempotency_key": key},
                    )
                return existing["run_id"]

            run_id = create()
            records[key] = {"signature": signature, "run_id": run_id}
            atomic_write_json(self._path, records)
            return run_id
