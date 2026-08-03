"""Small state helpers kept dependency-free to avoid import cycles."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
