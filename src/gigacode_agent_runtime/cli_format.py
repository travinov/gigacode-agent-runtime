"""CLI-only rendering and stable exit-code mapping."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping

from .domain import RunStatus
from .errors import AgentRuntimeError, ErrorCode

EXIT_SUCCESS = 0
EXIT_INVALID = 2
EXIT_PERMISSION = 3
EXIT_RUNTIME = 4
EXIT_STOPPED = 5
EXIT_INTERNAL = 10

_INVALID_CODES = {
    ErrorCode.CONFIG_INVALID,
    ErrorCode.SCENARIO_INVALID,
    ErrorCode.SCHEMA_INVALID,
    ErrorCode.MODEL_NOT_ALLOWED,
    ErrorCode.PATH_NOT_ALLOWED,
    ErrorCode.IDEMPOTENCY_CONFLICT,
    ErrorCode.INVALID_STATE_TRANSITION,
    ErrorCode.INPUT_NOT_EXPECTED,
}
_PERMISSION_CODES = {
    ErrorCode.PERMISSION_DENIED,
    ErrorCode.APPROVAL_REQUIRED,
}


def error_exit_code(error: AgentRuntimeError) -> int:
    if error.code in _INVALID_CODES:
        return EXIT_INVALID
    if error.code in _PERMISSION_CODES:
        return EXIT_PERMISSION
    if error.code is ErrorCode.INTERNAL_ERROR:
        return EXIT_INTERNAL
    return EXIT_RUNTIME


def state_exit_code(status: RunStatus) -> int:
    if status in {RunStatus.INTERRUPTED, RunStatus.CANCELLED}:
        return EXIT_STOPPED
    if status is RunStatus.WAITING_FOR_APPROVAL:
        return EXIT_PERMISSION
    if status is RunStatus.FAILED:
        return EXIT_RUNTIME
    return EXIT_SUCCESS


def emit(
    document: object,
    *,
    as_json: bool,
    human: str | None = None,
) -> None:
    if as_json:
        print(json.dumps(document, ensure_ascii=False, sort_keys=True))
        return
    if human is not None:
        print(human)
    elif isinstance(document, Mapping):
        for key, value in document.items():
            print(f"{key}: {value}")
    else:
        print(document)


def emit_error(error: AgentRuntimeError, *, as_json: bool) -> int:
    if as_json:
        print(
            json.dumps(
                {"ok": False, "error": error.to_dict()},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        print(f"{error.code.value}: {error.message}", file=sys.stderr)
    return error_exit_code(error)
