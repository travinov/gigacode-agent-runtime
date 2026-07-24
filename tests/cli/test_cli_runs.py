from __future__ import annotations

import json
from pathlib import Path

from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.domain import RunStatus
from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.state_store import StateStore
from tests.cli.conftest import cli_environment, run_cli

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


def test_foreground_run_status_events_and_result(tmp_path: Path) -> None:
    executed = run_cli(
        tmp_path,
        "run",
        str(SCENARIOS / "sequential-valid.yaml"),
        "--workspace",
        str(tmp_path),
        "--json",
    )
    state = json.loads(executed.stdout)
    run_id = state["run_id"]
    status = run_cli(tmp_path, "status", run_id, "--json")
    events = run_cli(tmp_path, "events", run_id, "--limit", "2", "--json")
    result = run_cli(tmp_path, "result", run_id, "--json")

    assert executed.returncode == 0
    assert state["status"] == "completed"
    assert json.loads(status.stdout)["status"] == "completed"
    assert len(json.loads(events.stdout)["events"]) == 2
    assert json.loads(result.stdout)["result"]["summary"] == "fake success"


def test_resume_and_cancel_use_durable_state(tmp_path: Path) -> None:
    config_path, _environment = cli_environment(tmp_path)
    config = load_config(config_path, home=tmp_path / "home")
    service = RuntimeService(config)
    prepared = service.start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )
    states = StateStore(config.paths.runs)
    states.transition(prepared.run_id, RunStatus.RUNNING)
    states.transition(prepared.run_id, RunStatus.INTERRUPTED)

    resumed = run_cli(tmp_path, "resume", prepared.run_id, "--json")
    resumed_state = json.loads(resumed.stdout)
    pending = service.start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )
    cancelled = run_cli(tmp_path, "cancel", pending.run_id, "--json")

    assert resumed.returncode == 0
    assert resumed_state["status"] == "completed"
    assert cancelled.returncode == 5
    assert json.loads(cancelled.stdout)["status"] == "cancelled"
