from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.scheduler import DagScheduler
from tests.helpers.scheduler import agent_traces, scheduler_adapter, scheduler_config

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_sequential_steps_do_not_overlap(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )

    result = await DagScheduler(config, scheduler_adapter(tmp_path, "delayed")).run(
        prepared
    )
    traces = agent_traces(tmp_path)

    assert result.state.status.value == "completed"
    assert len(traces) == 2
    assert traces[0]["end_monotonic"] <= traces[1]["start_monotonic"]
