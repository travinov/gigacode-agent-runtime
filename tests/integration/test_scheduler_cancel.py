from __future__ import annotations

from pathlib import Path

import anyio
import pytest

from gigacode_agent_runtime.cancellation import ExecutionControl
from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.scheduler import DagScheduler
from tests.helpers.scheduler import scheduler_adapter, scheduler_config

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_cancel_terminates_active_process_groups_and_run(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )
    control = ExecutionControl()
    holder = {}

    async def execute() -> None:
        holder["result"] = await DagScheduler(
            config,
            scheduler_adapter(
                tmp_path,
                "ignore-sigterm",
                graceful_cancel_seconds=0.05,
            ),
        ).run(prepared, control=control)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(execute)
        await anyio.sleep(0.15)
        control.cancel()

    result = holder["result"]
    assert result.state.status.value == "cancelled"
    assert result.state.steps["create"].status.value == "cancelled"
    assert "step.cancelled" in [
        event.type for event in prepared.events.read().events
    ]


@pytest.mark.anyio
async def test_pause_waits_for_active_step_and_starts_no_new_step(
    tmp_path: Path,
) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )
    control = ExecutionControl()
    holder = {}

    async def execute() -> None:
        holder["result"] = await DagScheduler(
            config,
            scheduler_adapter(tmp_path, "delayed"),
        ).run(prepared, control=control)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(execute)
        await anyio.sleep(0.1)
        control.pause()

    result = holder["result"]
    assert result.state.status.value == "paused"
    assert result.state.steps["create"].status.value == "completed"
    assert "review" not in result.state.steps
