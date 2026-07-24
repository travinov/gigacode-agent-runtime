from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.scheduler import DagScheduler
from tests.helpers.scheduler import scheduler_adapter, scheduler_config

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_failure_blocks_downstream_and_preserves_events(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )

    result = await DagScheduler(config, scheduler_adapter(tmp_path, "permanent")).run(
        prepared
    )
    event_types = [event.type for event in prepared.events.read().events]

    assert result.state.status.value == "failed"
    assert result.state.steps["create"].status.value == "failed"
    assert result.state.steps["review"].status.value == "blocked"
    assert "run.failed" in event_types


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("profile", "retry_reason"),
    [
        ("transient", "transient_cli_error"),
        ("invalid-transient", "invalid_output"),
    ],
)
async def test_retry_recovers_without_changing_business_iteration(
    tmp_path: Path,
    profile: str,
    retry_reason: str,
) -> None:
    scenario_path = tmp_path / "retry.yaml"
    scenario_path.write_text(
        f"""
schema_version: gigacode-agent-runtime/scenario-v1
kind: Scenario
metadata:
  name: retry
  title: Retry
agents:
  worker:
    model: code-model-id
    permissions: read_only
    system_prompt: Work.
steps:
  work:
    kind: agent
    agent: worker
    needs: []
    prompt: {{template: Work.}}
    output_schema: {{type: object}}
    retry:
      max_attempts: 2
      backoff_seconds: [0]
      on: [{retry_reason}]
result:
  from: "${{steps.work.output}}"
""".lstrip()
    )
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(scenario_path),
        inputs={},
        workspace=tmp_path,
    )

    result = await DagScheduler(config, scheduler_adapter(tmp_path, profile)).run(
        prepared
    )

    assert result.state.status.value == "completed"
    assert result.state.steps["work"].attempt == 2
    assert result.state.steps["work"].iteration is None
    assert [
        event.type for event in prepared.events.read().events
    ].count("step.retrying") == 1
