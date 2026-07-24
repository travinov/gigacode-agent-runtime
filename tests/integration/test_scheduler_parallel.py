from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.approval_store import ApprovalStore
from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.scheduler import DagScheduler
from tests.helpers.scheduler import agent_traces, scheduler_adapter, scheduler_config

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_parallel_wave_really_overlaps_and_respects_limit(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path, max_parallel=2)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(SCENARIOS / "parallel-valid.yaml"),
        inputs={"task": "compare"},
        workspace=tmp_path,
    )

    result = await DagScheduler(config, scheduler_adapter(tmp_path, "delayed")).run(
        prepared
    )
    traces = agent_traces(tmp_path)
    first_wave = sorted(traces[:2], key=lambda trace: trace["start_monotonic"])

    assert result.state.status.value == "completed"
    assert len(traces) == 3
    assert first_wave[1]["start_monotonic"] < first_wave[0]["end_monotonic"]
    assert traces[2]["start_monotonic"] >= max(
        trace["end_monotonic"] for trace in traces[:2]
    )


@pytest.mark.anyio
async def test_full_access_has_independent_parallel_limit(tmp_path: Path) -> None:
    scenario_path = tmp_path / "full-parallel.yaml"
    scenario_path.write_text(
        """
schema_version: gigacode-agent-runtime/scenario-v1
kind: Scenario
metadata:
  name: full-parallel
  title: Full access parallel limit
agents:
  worker:
    model: code-model-id
    permissions: full_access
    system_prompt: Work.
    allowed_tools: [read_file]
steps:
  first:
    kind: agent
    agent: worker
    needs: []
    prompt: {template: First.}
    output_schema: {type: object}
  second:
    kind: agent
    agent: worker
    needs: []
    prompt: {template: Second.}
    output_schema: {type: object}
result:
  from: "${steps.second.output}"
""".lstrip()
    )
    config = scheduler_config(
        tmp_path,
        max_parallel=2,
        allow_full_access=True,
        max_parallel_full_access=1,
    )
    prepared = RuntimeService(config).start_run(
        load_scenario_file(scenario_path),
        inputs={},
        workspace=tmp_path,
    )
    ApprovalStore(prepared.run_dir).approve(
        prepared.run_id,
        prepared.plan.plan_hash,
        "full_access",
    )

    result = await DagScheduler(config, scheduler_adapter(tmp_path, "delayed")).run(
        prepared
    )
    traces = sorted(agent_traces(tmp_path), key=lambda trace: trace["start_monotonic"])

    assert result.state.status.value == "completed"
    assert len(traces) == 2
    assert traces[0]["end_monotonic"] <= traces[1]["start_monotonic"]
