from __future__ import annotations

import json
from pathlib import Path

import pytest

from gigacode_agent_runtime.artifacts import ArtifactStore
from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file

FIXTURES = Path(__file__).parents[1] / "fixtures" / "scenarios"


def test_complete_snapshot_exists_before_execution(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.yaml", home=tmp_path / "home")
    service = RuntimeService(config)
    prepared = service.start_run(
        load_scenario_file(FIXTURES / "parallel-valid.yaml"),
        inputs={"task": "compare"},
        workspace=tmp_path,
    )

    expected = {
        "scenario.snapshot.yaml",
        "effective-config.snapshot.yaml",
        "execution-plan.json",
        "capability-requirements.json",
        "run.json",
        "events.jsonl",
    }
    assert expected <= {path.name for path in prepared.run_dir.iterdir()}
    assert json.loads((prepared.run_dir / "inputs" / "input.json").read_text()) == {
        "task": "compare"
    }


def test_external_scenario_change_does_not_change_snapshot(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text((FIXTURES / "sequential-valid.yaml").read_text())
    scenario = load_scenario_file(scenario_path)
    service = RuntimeService(load_config(tmp_path / "missing.yaml", home=tmp_path / "home"))
    prepared = service.start_run(scenario, inputs={}, workspace=tmp_path)
    snapshot_before = (prepared.run_dir / "scenario.snapshot.yaml").read_text()

    scenario_path.write_text("changed externally")

    assert (prepared.run_dir / "scenario.snapshot.yaml").read_text() == snapshot_before


def test_artifact_path_traversal_is_blocked(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(AgentRuntimeError) as captured:
        store.write_text("../outside.txt", "unsafe", mime_type="text/plain")

    assert captured.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert not (tmp_path.parent / "outside.txt").exists()


def test_result_before_completion_is_typed_nonterminal_response(tmp_path: Path) -> None:
    service = RuntimeService(load_config(tmp_path / "missing.yaml", home=tmp_path / "home"))
    prepared = service.start_run(
        load_scenario_file(FIXTURES / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )

    result = service.get_result(prepared.run_id)

    assert result == {"run_id": prepared.run_id, "status": "planned", "result": None}
