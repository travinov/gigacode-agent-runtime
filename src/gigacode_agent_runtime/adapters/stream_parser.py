"""Normalize GigaCode JSON and stream-JSON responses."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from ..errors import AgentRuntimeError, ErrorCode


@dataclass(frozen=True, slots=True)
class ParsedStream:
    events: tuple[Mapping[str, object], ...]
    result: Mapping[str, object]


def _invalid_output(message: str, *, line: int | None = None) -> AgentRuntimeError:
    details: dict[str, object] = {}
    if line is not None:
        details["line"] = line
    return AgentRuntimeError(
        ErrorCode.STEP_OUTPUT_INVALID,
        message,
        details=details,
        retryable=True,
    )


class StreamJsonParser:
    def __init__(self) -> None:
        self._buffer = ""
        self._lines: list[str] = []

    def feed(self, chunk: str) -> None:
        self._buffer += chunk
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._lines.append(line)

    def finish(self) -> ParsedStream:
        if self._buffer.strip():
            self._lines.append(self._buffer)
        events: list[Mapping[str, object]] = []
        result: Mapping[str, object] | None = None
        for line_number, line in enumerate(self._lines, start=1):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise _invalid_output(
                    "GigaCode emitted invalid stream JSON",
                    line=line_number,
                ) from exc
            if not isinstance(parsed, dict):
                raise _invalid_output(
                    "GigaCode stream event must be an object",
                    line=line_number,
                )
            event = MappingProxyType(cast(dict[str, object], parsed))
            events.append(event)
            if parsed.get("type") == "result":
                candidate = parsed.get("result")
                if not isinstance(candidate, dict):
                    raise _invalid_output(
                        "GigaCode result event must contain an object",
                        line=line_number,
                    )
                result = MappingProxyType(cast(dict[str, object], candidate))
        if result is None:
            raise _invalid_output("GigaCode stream ended without a result event")
        return ParsedStream(events=tuple(events), result=result)


def parse_json_result(text: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _invalid_output("GigaCode emitted invalid JSON") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("result"), dict):
        raise _invalid_output("GigaCode JSON output must contain an object result")
    return MappingProxyType(cast(dict[str, Any], parsed["result"]))
