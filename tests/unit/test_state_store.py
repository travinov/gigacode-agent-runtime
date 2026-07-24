from __future__ import annotations

import os
from pathlib import Path

import pytest

from gigacode_agent_runtime.domain import RunStatus
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.event_log import EventLog
from gigacode_agent_runtime.state_store import StateStore

PLAN_HASH = "sha256:" + ("b" * 64)


def test_create_and_read_run_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path)

    state = store.create(PLAN_HASH)
    loaded = store.read(state.run_id)

    assert loaded == state
    assert loaded.status is RunStatus.VALIDATING


def test_invalid_transition_does_not_change_persisted_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    state = store.create(PLAN_HASH)
    store.transition(state.run_id, RunStatus.FAILED)
    before = (store.run_dir(state.run_id) / "run.json").read_bytes()

    with pytest.raises(AgentRuntimeError) as captured:
        store.transition(state.run_id, RunStatus.RUNNING)

    assert captured.value.code is ErrorCode.INVALID_STATE_TRANSITION
    assert (store.run_dir(state.run_id) / "run.json").read_bytes() == before


def test_failed_replace_preserves_previous_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StateStore(tmp_path)
    state = store.create(PLAN_HASH)
    before = (store.run_dir(state.run_id) / "run.json").read_bytes()

    def fail_replace(source: str | bytes | os.PathLike[str] | os.PathLike[bytes], target: str):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        store.transition(state.run_id, RunStatus.PLANNED)

    assert (store.run_dir(state.run_id) / "run.json").read_bytes() == before


def test_corrupted_state_is_preserved_for_forensics(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    state = store.create(PLAN_HASH)
    state_path = store.run_dir(state.run_id) / "run.json"
    state_path.write_text("{broken")

    with pytest.raises(AgentRuntimeError) as captured:
        store.read(state.run_id)

    assert captured.value.code is ErrorCode.STATE_CORRUPTED
    assert state_path.read_text() == "{broken"
    assert list(store.run_dir(state.run_id).glob("run.corrupt.*.json"))


def test_recovery_marks_running_run_interrupted(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    state = store.create(PLAN_HASH)
    store.transition(state.run_id, RunStatus.PLANNED)
    store.transition(state.run_id, RunStatus.RUNNING)
    events = EventLog(store.run_dir(state.run_id), run_id=state.run_id)

    recovered = store.recover_interrupted(state.run_id, events)

    assert recovered.status is RunStatus.INTERRUPTED
    assert events.read().events[-1].type == "run.interrupted"


def test_run_id_cannot_escape_runs_directory(tmp_path: Path) -> None:
    store = StateStore(tmp_path)

    with pytest.raises(AgentRuntimeError) as captured:
        store.read("../../outside")

    assert captured.value.code is ErrorCode.RUN_NOT_FOUND
