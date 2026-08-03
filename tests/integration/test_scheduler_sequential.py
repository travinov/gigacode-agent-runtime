from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.agent_catalog import AgentProfileCatalog
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


@pytest.mark.anyio
async def test_reusable_agent_profile_executes_through_normal_scheduler(
    tmp_path: Path,
) -> None:
    config = scheduler_config(tmp_path)
    agents = tmp_path / "home" / ".gigacode" / "agents"
    agents.mkdir(parents=True)
    (agents / "analyst.md").write_text(
        "---\n"
        "name: reusable-analyst\n"
        "description: Reusable analyst.\n"
        "---\n\n"
        "REUSABLE_AGENT_PROMPT_MARKER\n"
    )
    scenario_path = tmp_path / "agent-ref.yaml"
    scenario_path.write_text(
        (SCENARIOS / "sequential-valid.yaml").read_text().replace(
            "system_prompt: Create a structured draft.",
            "agent_ref: gigacode:reusable-analyst",
        )
    )
    scenario = load_scenario_file(
        scenario_path,
        agent_catalog=AgentProfileCatalog(agents),
    )
    prepared = RuntimeService(config).start_run(
        scenario,
        inputs={},
        workspace=tmp_path,
    )

    result = await DagScheduler(config, scheduler_adapter(tmp_path, "success")).run(
        prepared
    )
    traces = agent_traces(tmp_path)

    assert result.state.status.value == "completed"
    assert result.state.result == {"summary": "fake success", "approved": True}
    assert len(traces) == 2
    assert prepared.plan.agents["creator"].system_prompt == (
        "REUSABLE_AGENT_PROMPT_MARKER"
    )
    assert prepared.plan.agents["creator"].source_ref == (
        "gigacode:reusable-analyst"
    )
