from __future__ import annotations

from dataclasses import replace

import pytest

from gigacode_agent_runtime.domain import RunState, RunStatus
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.state_machine import transition_run
from gigacode_agent_runtime.version import RUN_STATE_SCHEMA_VERSION


def _state(status: RunStatus) -> RunState:
    return RunState(
        schema_version=RUN_STATE_SCHEMA_VERSION,
        run_id="run_20260724T120000000000Z_aaaaaaaaaaaa",
        plan_hash="sha256:" + ("a" * 64),
        status=status,
        created_at="2026-07-24T12:00:00.000000Z",
        updated_at="2026-07-24T12:00:00.000000Z",
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.VALIDATING, RunStatus.PLANNED),
        (RunStatus.PLANNED, RunStatus.RUNNING),
        (RunStatus.PLANNED, RunStatus.WAITING_FOR_APPROVAL),
        (RunStatus.RUNNING, RunStatus.WAITING_FOR_INPUT),
        (RunStatus.RUNNING, RunStatus.PAUSED),
        (RunStatus.RUNNING, RunStatus.INTERRUPTED),
        (RunStatus.INTERRUPTED, RunStatus.RUNNING),
        (RunStatus.PAUSED, RunStatus.RUNNING),
        (RunStatus.RUNNING, RunStatus.COMPLETED),
        (RunStatus.RUNNING, RunStatus.COMPLETED_BEST_EFFORT),
        (RunStatus.RUNNING, RunStatus.FAILED),
        (RunStatus.RUNNING, RunStatus.CANCELLED),
    ],
)
def test_allowed_transitions(current: RunStatus, target: RunStatus) -> None:
    transitioned = transition_run(
        _state(current),
        target,
        updated_at="2026-07-24T12:01:00.000000Z",
    )

    assert transitioned.status is target
    assert transitioned.updated_at == "2026-07-24T12:01:00.000000Z"


def test_invalid_transition_preserves_original_state() -> None:
    original = _state(RunStatus.COMPLETED)

    with pytest.raises(AgentRuntimeError) as captured:
        transition_run(
            original,
            RunStatus.RUNNING,
            updated_at="2026-07-24T12:01:00.000000Z",
        )

    assert captured.value.code is ErrorCode.INVALID_STATE_TRANSITION
    assert original == replace(original)
