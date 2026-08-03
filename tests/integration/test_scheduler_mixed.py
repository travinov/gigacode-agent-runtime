from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.scheduler import DagScheduler
from tests.helpers.scheduler import scheduler_adapter, scheduler_config

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_fan_in_receives_both_upstream_outputs(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(SCENARIOS / "parallel-valid.yaml"),
        inputs={"task": "compare"},
        workspace=tmp_path,
    )

    result = await DagScheduler(config, scheduler_adapter(tmp_path, "success")).run(
        prepared
    )

    assert result.state.result is not None
    assert result.state.result["summary"] == "fake success"
    assert {
        name
        for name, step in result.state.steps.items()
        if step.status.value == "completed"
    } == {"analyze_first", "analyze_second", "review"}
