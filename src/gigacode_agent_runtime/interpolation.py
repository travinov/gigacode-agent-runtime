"""Restricted one-pass interpolation for scenario data."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence

from .errors import AgentRuntimeError, ErrorCode

_REFERENCE = re.compile(r"\$\{([^{}]+)\}")


def _is_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value))


def _is_allowed_reference(reference: str) -> bool:
    parts = reference.split(".")
    if len(parts) >= 2 and parts[0] == "inputs" and _is_identifier(parts[1]):
        return all(part for part in parts[2:])
    if (
        len(parts) >= 3
        and parts[0] == "steps"
        and _is_identifier(parts[1])
        and parts[2] == "output"
    ):
        return all(part for part in parts[3:])
    if parts == ["loop", "iteration"]:
        return True
    if (
        len(parts) >= 4
        and parts[0] == "loop"
        and parts[1] in {"previous", "steps", "previous_or_initial"}
        and _is_identifier(parts[2])
        and parts[3] == "output"
    ):
        return all(part for part in parts[4:])
    return parts in (["run", "id"], ["workspace", "root"])


def extract_references(template: str) -> tuple[str, ...]:
    return tuple(match.group(1) for match in _REFERENCE.finditer(template))


def validate_template(template: str) -> None:
    for reference in extract_references(template):
        if not _is_allowed_reference(reference):
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Unsupported interpolation reference: {reference}",
                details={"reference": reference},
            )


def _stringify_embedded(value: object) -> str:
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def interpolate(template: str, resolver: Callable[[str], object]) -> object:
    """Resolve each original reference exactly once."""

    validate_template(template)
    full = _REFERENCE.fullmatch(template)
    if full is not None:
        return resolver(full.group(1))

    parts: list[str] = []
    cursor = 0
    for match in _REFERENCE.finditer(template):
        parts.append(template[cursor : match.start()])
        parts.append(_stringify_embedded(resolver(match.group(1))))
        cursor = match.end()
    parts.append(template[cursor:])
    return "".join(parts)
