from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.domain import RunStatus
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.input_gates import InputGateStore
from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.state_store import StateStore
from tests.helpers.scheduler import scheduler_config

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


def _running_gate(tmp_path: Path) -> tuple[InputGateStore, StateStore, str]:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )
    states = StateStore(config.paths.runs)
    states.transition(prepared.run_id, RunStatus.RUNNING)
    return InputGateStore(config.paths.runs, prepared.run_id), states, prepared.run_id


def test_provide_input_validates_schema_and_resumes_run(tmp_path: Path) -> None:
    gate, states, run_id = _running_gate(tmp_path)
    gate.request(
        "decision",
        prompt="Continue?",
        input_schema={"type": "object", "required": ["approved"]},
    )

    with pytest.raises(AgentRuntimeError) as captured:
        gate.provide("decision", {"wrong": True})

    assert captured.value.code is ErrorCode.SCHEMA_INVALID
    provided = gate.provide("decision", {"approved": True})
    assert provided["value"] == {"approved": True}
    assert states.read(run_id).status is RunStatus.RUNNING


def test_provide_input_only_accepts_active_gate(tmp_path: Path) -> None:
    gate, _states, _run_id = _running_gate(tmp_path)

    with pytest.raises(AgentRuntimeError) as captured:
        gate.provide("decision", {"approved": True})

    assert captured.value.code is ErrorCode.INPUT_NOT_EXPECTED
