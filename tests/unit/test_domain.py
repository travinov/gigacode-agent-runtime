from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from gigacode_agent_runtime.domain import (
    OnLimit,
    PermissionMode,
    RetryPolicy,
    RunStatus,
    StepStatus,
)
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode


def test_public_enum_values_match_persisted_contract() -> None:
    assert {status.value for status in RunStatus} == {
        "validating",
        "planned",
        "running",
        "waiting_for_input",
        "waiting_for_approval",
        "paused",
        "interrupted",
        "completed",
        "completed_best_effort",
        "failed",
        "cancelled",
    }
    assert PermissionMode.FULL_ACCESS.value == "full_access"
    assert OnLimit.BEST_EFFORT.value == "best_effort"
    assert StepStatus.BLOCKED.value == "blocked"


def test_domain_records_are_immutable() -> None:
    policy = RetryPolicy(max_attempts=3, backoff_seconds=(1.0, 5.0))

    with pytest.raises(FrozenInstanceError):
        policy.max_attempts = 4  # type: ignore[misc]


def test_typed_error_has_safe_serializable_shape() -> None:
    error = AgentRuntimeError(
        ErrorCode.CONFIG_INVALID,
        "invalid configuration",
        details={"path": "/runtime/max_parallel_agents"},
        retryable=False,
    )

    assert error.to_dict() == {
        "code": "CONFIG_INVALID",
        "message": "invalid configuration",
        "details": {"path": "/runtime/max_parallel_agents"},
        "retryable": False,
    }
