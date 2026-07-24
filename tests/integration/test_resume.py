from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.domain import RunStatus, StepState, StepStatus
from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.scheduler import DagScheduler
from gigacode_agent_runtime.state_store import StateStore
from tests.helpers.scheduler import agent_traces, scheduler_adapter, scheduler_config
from tests.integration.test_loop_review_repair import _scenario as loop_scenario

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_resume_uses_snapshot_and_does_not_repeat_completed_step(
    tmp_path: Path,
) -> None:
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text((SCENARIOS / "sequential-valid.yaml").read_text())
    config = scheduler_config(tmp_path)
    service = RuntimeService(config)
    prepared = service.start_run(
        load_scenario_file(scenario_path),
        inputs={},
        workspace=tmp_path,
    )
    states = StateStore(config.paths.runs)
    states.put_step(
        prepared.run_id,
        StepState(
            instance_id="create",
            status=StepStatus.COMPLETED,
            attempt=1,
            output={"summary": "already complete"},
        ),
    )
    states.transition(prepared.run_id, RunStatus.RUNNING)
    states.transition(prepared.run_id, RunStatus.INTERRUPTED)
    scenario_path.write_text("changed externally and no longer valid")

    resumed = service.prepare_resume(prepared.run_id)
    result = await DagScheduler(
        resumed.config,
        scheduler_adapter(tmp_path, "success"),
    ).run(resumed)

    assert result.state.status.value == "completed"
    assert result.state.steps["create"].output == {"summary": "already complete"}
    assert len(agent_traces(tmp_path)) == 1
    assert [
        event.payload.get("step")
        for event in resumed.events.read().events
        if event.type == "step.started"
    ] == ["review"]


@pytest.mark.anyio
async def test_resume_continues_current_loop_iteration(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path)
    service = RuntimeService(config)
    prepared = service.start_run(
        load_scenario_file(loop_scenario(tmp_path / "loop.yaml")),
        inputs={},
        workspace=tmp_path,
    )
    states = StateStore(config.paths.runs)
    states.put_step(
        prepared.run_id,
        StepState(
            instance_id="review@iteration-1",
            status=StepStatus.COMPLETED,
            attempt=1,
            iteration=1,
            output={"approved": False, "feedback": "repair"},
        ),
    )
    states.put_step(
        prepared.run_id,
        StepState(
            instance_id="repair@iteration-1",
            status=StepStatus.INTERRUPTED,
            attempt=1,
            iteration=1,
        ),
    )
    states.put_step(
        prepared.run_id,
        StepState(
            instance_id="improve",
            status=StepStatus.INTERRUPTED,
            attempt=1,
            iteration=1,
        ),
    )
    states.transition(prepared.run_id, RunStatus.RUNNING)
    states.transition(prepared.run_id, RunStatus.INTERRUPTED)

    resumed = service.prepare_resume(prepared.run_id)
    result = await DagScheduler(
        resumed.config,
        scheduler_adapter(tmp_path, "resume-loop"),
    ).run(resumed)

    assert result.state.status.value == "completed"
    assert result.state.steps["review@iteration-1"].attempt == 1
    assert result.state.steps["repair@iteration-1"].status.value == "completed"
    assert result.state.steps["review@iteration-2"].status.value == "completed"
    assert len(agent_traces(tmp_path)) == 2
