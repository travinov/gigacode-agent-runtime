"""Normalize GigaCode JSON and stream-JSON responses."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

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


def _parse_object(value: object, *, source: str, line: int | None = None) -> Mapping[str, object]:
    if isinstance(value, dict):
        return MappingProxyType(cast(dict[str, object], value))
    if not isinstance(value, str):
        raise _invalid_output(f"{source} must contain a JSON object", line=line)

    payload = value.strip()
    if payload.startswith("```") or payload.endswith("```"):
        fenced = re.fullmatch(
            r"```(?:json)?[ \t]*\r?\n(?P<payload>[\s\S]*?)\r?\n```",
            payload,
            flags=re.IGNORECASE,
        )
        if fenced is None or "```" in fenced.group("payload"):
            raise _invalid_output(
                f"{source} has an ambiguous Markdown JSON fence",
                line=line,
            )
        payload = fenced.group("payload").strip()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise _invalid_output(f"{source} is not valid JSON", line=line) from exc
    if not isinstance(parsed, dict):
        raise _invalid_output(f"{source} must decode to a JSON object", line=line)
    return MappingProxyType(cast(dict[str, object], parsed))


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
                if parsed.get("is_error") is True:
                    raise _invalid_output(
                        "GigaCode result event reports an error",
                        line=line_number,
                    )
                candidate = parsed.get("result")
                result = _parse_object(
                    candidate,
                    source="GigaCode result event",
                    line=line_number,
                )
        if result is None:
            raise _invalid_output("GigaCode stream ended without a result event")
        return ParsedStream(events=tuple(events), result=result)


def parse_json_result(text: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _invalid_output("GigaCode emitted invalid JSON") from exc
    if not isinstance(parsed, dict) or "result" not in parsed:
        raise _invalid_output("GigaCode JSON output must contain a result")
    return _parse_object(parsed["result"], source="GigaCode JSON result")
