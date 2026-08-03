"""Normalize GigaCode JSON and stream-JSON responses."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from ..errors import AgentRuntimeError, ErrorCode

_API_ERROR_PATTERN = re.compile(
    r"\A\[API Error:\s*(?:(?P<status>\d{3})\s+)?(?P<message>[\s\S]*?)\]\Z",
    flags=re.IGNORECASE,
)
_RETRYABLE_API_STATUS_CODES = {408, 409, 425, 429}


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


def _api_error(payload: str, *, line: int | None = None) -> AgentRuntimeError | None:
    matched = _API_ERROR_PATTERN.fullmatch(payload)
    if matched is None:
        return None
    status_text = matched.group("status")
    status_code = int(status_text) if status_text is not None else None
    api_message = matched.group("message").strip().casefold()
    model_not_found = status_code == 404 and "model not found" in api_message
    details: dict[str, object] = {}
    if line is not None:
        details["line"] = line
    if status_code is not None:
        details["status_code"] = status_code
    retryable = bool(
        status_code in _RETRYABLE_API_STATUS_CODES
        or (status_code is not None and status_code >= 500)
    )
    return AgentRuntimeError(
        ErrorCode.PROCESS_ERROR,
        (
            "GigaCode API model was not found"
            if model_not_found
            else "GigaCode API request failed"
        ),
        details=details,
        retryable=retryable,
    )


def _parse_object(value: object, *, source: str, line: int | None = None) -> Mapping[str, object]:
    if isinstance(value, dict):
        return MappingProxyType(cast(dict[str, object], value))
    if not isinstance(value, str):
        raise _invalid_output(f"{source} must contain a JSON object", line=line)

    payload = value.strip()
    api_error = _api_error(payload, line=line)
    if api_error is not None:
        raise api_error
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
        api_error = _api_error(payload, line=line)
        if api_error is not None:
            raise api_error
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
