"""Stable typed errors shared by CLI, MCP, and Web surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


class ErrorCode(StrEnum):
    CONFIG_INVALID = "CONFIG_INVALID"
    SCENARIO_INVALID = "SCENARIO_INVALID"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    SCHEMA_NOT_FOUND = "SCHEMA_NOT_FOUND"
    PLAN_CONFLICT = "PLAN_CONFLICT"
    MODEL_NOT_ALLOWED = "MODEL_NOT_ALLOWED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    STEP_OUTPUT_INVALID = "STEP_OUTPUT_INVALID"
    STATE_CORRUPTED = "STATE_CORRUPTED"
    PATH_NOT_ALLOWED = "PATH_NOT_ALLOWED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AgentRuntimeError(Exception):
    """An expected runtime failure with a stable public error code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = MappingProxyType(dict(details or {}))
        self.retryable = retryable

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": dict(self.details),
            "retryable": self.retryable,
        }
