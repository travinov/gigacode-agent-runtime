"""Central run-state transition rules."""

from __future__ import annotations

from dataclasses import replace

from .domain import RunState, RunStatus
from .errors import AgentRuntimeError, ErrorCode

_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.VALIDATING: frozenset(
        {RunStatus.PLANNED, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.PLANNED: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.WAITING_FOR_APPROVAL,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.WAITING_FOR_APPROVAL: frozenset(
        {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_FOR_INPUT,
            RunStatus.PAUSED,
            RunStatus.INTERRUPTED,
            RunStatus.COMPLETED,
            RunStatus.COMPLETED_BEST_EFFORT,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.WAITING_FOR_INPUT: frozenset(
        {RunStatus.RUNNING, RunStatus.INTERRUPTED, RunStatus.CANCELLED}
    ),
    RunStatus.PAUSED: frozenset(
        {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED}
    ),
    RunStatus.INTERRUPTED: frozenset(
        {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED}
    ),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.COMPLETED_BEST_EFFORT: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def transition_run(
    state: RunState,
    target: RunStatus,
    *,
    updated_at: str,
) -> RunState:
    if target not in _TRANSITIONS[state.status]:
        raise AgentRuntimeError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Cannot transition run from {state.status.value} to {target.value}",
            details={"current": state.status.value, "target": target.value},
        )
    return replace(state, status=target, updated_at=updated_at)
