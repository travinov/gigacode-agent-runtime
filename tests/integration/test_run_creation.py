from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file

FIXTURES = Path(__file__).parents[1] / "fixtures" / "scenarios"


def _service(tmp_path: Path) -> RuntimeService:
    config = load_config(tmp_path / "missing.yaml", home=tmp_path / "home")
    return RuntimeService(config)


def test_start_run_creates_planned_state_and_events(tmp_path: Path) -> None:
    service = _service(tmp_path)
    scenario = load_scenario_file(FIXTURES / "parallel-valid.yaml")

    prepared = service.start_run(
        scenario,
        inputs={"task": "compare"},
        workspace=tmp_path,
        idempotency_key="request-1",
    )

    assert prepared.state.status.value == "planned"
    assert prepared.run_dir.is_dir()
    assert [event.type for event in prepared.events.read().events] == [
        "run.created",
        "plan.compiled",
    ]


def test_idempotent_start_returns_same_run(tmp_path: Path) -> None:
    service = _service(tmp_path)
    scenario = load_scenario_file(FIXTURES / "parallel-valid.yaml")

    first = service.start_run(
        scenario,
        inputs={"task": "compare"},
        workspace=tmp_path,
        idempotency_key="request-1",
    )
    second = service.start_run(
        scenario,
        inputs={"task": "compare"},
        workspace=tmp_path,
        idempotency_key="request-1",
    )

    assert second.run_id == first.run_id


def test_idempotency_conflict_does_not_create_second_run(tmp_path: Path) -> None:
    service = _service(tmp_path)
    scenario = load_scenario_file(FIXTURES / "parallel-valid.yaml")
    service.start_run(
        scenario,
        inputs={"task": "first"},
        workspace=tmp_path,
        idempotency_key="request-1",
    )
    runs_before = set(service.config.paths.runs.iterdir())

    with pytest.raises(AgentRuntimeError) as captured:
        service.start_run(
            scenario,
            inputs={"task": "different"},
            workspace=tmp_path,
            idempotency_key="request-1",
        )

    assert captured.value.code is ErrorCode.IDEMPOTENCY_CONFLICT
    assert set(service.config.paths.runs.iterdir()) == runs_before
