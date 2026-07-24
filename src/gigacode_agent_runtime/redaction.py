"""Conservative secret redaction for diagnostics and persisted stderr."""

from __future__ import annotations

import re
from collections.abc import Iterable

_TOKEN_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)\b(token|secret|password|api[_-]?key)=([^\s]+)"),
)


class Redactor:
    def __init__(self, secret_values: Iterable[str] = ()) -> None:
        self._secret_values = tuple(
            sorted({value for value in secret_values if value}, key=len, reverse=True)
        )

    def redact_text(self, text: str) -> str:
        redacted = text
        for value in self._secret_values:
            redacted = redacted.replace(value, "[REDACTED]")
        redacted = _TOKEN_PATTERNS[0].sub(r"\1[REDACTED]", redacted)
        redacted = _TOKEN_PATTERNS[1].sub(r"\1=[REDACTED]", redacted)
        return redacted
