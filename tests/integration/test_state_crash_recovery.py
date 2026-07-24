from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.domain import RunStatus
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.locking import FileLock
from gigacode_agent_runtime.state_store import StateStore

PLAN_HASH = "sha256:" + ("c" * 64)


def test_only_one_writer_can_hold_run_lock(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    state = store.create(PLAN_HASH)
    lock_path = store.run_dir(state.run_id) / "writer.lock"

    with (
        FileLock(lock_path),
        pytest.raises(AgentRuntimeError) as captured,
        FileLock(lock_path),
    ):
        pass

    assert captured.value.code is ErrorCode.PLAN_CONFLICT


def test_completed_state_is_not_recovered_as_interrupted(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    state = store.create(PLAN_HASH)
    store.transition(state.run_id, RunStatus.PLANNED)
    store.transition(state.run_id, RunStatus.RUNNING)
    completed = store.transition(state.run_id, RunStatus.COMPLETED)

    recovered = store.recover_interrupted(state.run_id)

    assert recovered == completed
