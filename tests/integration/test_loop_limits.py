from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.scheduler import DagScheduler
from tests.helpers.scheduler import scheduler_adapter, scheduler_config


def _limit_scenario(path: Path, *, on_limit: str, no_progress: bool = False) -> Path:
    no_progress_yaml = (
        """
    no_progress:
      max_unchanged_iterations: 1
      fingerprint:
        - "${loop.steps.work.output.summary}"
"""
        if no_progress
        else ""
    )
    path.write_text(
        f"""
schema_version: gigacode-agent-runtime/scenario-v1
kind: Scenario
metadata:
  name: loop-{on_limit}
  title: Loop limit {on_limit}
agents:
  worker:
    model: code-model
    permissions: read_only
    system_prompt: Work.
steps:
  repeat:
    kind: loop
    needs: []
    max_iterations: 2
    timeout_seconds: 30
    on_limit: {on_limit}
{no_progress_yaml}    body:
      steps:
        work:
          kind: agent
          agent: worker
          needs: []
          prompt: {{template: Work.}}
          output_schema: {{type: object}}
    until:
      ref: "${{loop.steps.work.output.approved}}"
      op: eq
      value: false
result:
  from: "${{steps.repeat.output}}"
""".lstrip()
    )
    return path


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("on_limit", "expected"),
    [
        ("fail", "failed"),
        ("pause", "paused"),
        ("best_effort", "completed_best_effort"),
    ],
)
async def test_loop_max_iteration_policy(
    tmp_path: Path,
    on_limit: str,
    expected: str,
) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(_limit_scenario(tmp_path / "scenario.yaml", on_limit=on_limit)),
        inputs={},
        workspace=tmp_path,
    )

    result = await DagScheduler(config, scheduler_adapter(tmp_path, "success")).run(
        prepared
    )

    assert result.state.status.value == expected


@pytest.mark.anyio
async def test_no_progress_stops_at_exact_threshold(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(
            _limit_scenario(
                tmp_path / "scenario.yaml",
                on_limit="fail",
                no_progress=True,
            )
        ),
        inputs={},
        workspace=tmp_path,
    )

    result = await DagScheduler(config, scheduler_adapter(tmp_path, "success")).run(
        prepared
    )

    assert result.state.status.value == "failed"
    assert result.state.error is not None
    assert result.state.error["code"] == "NO_PROGRESS"
    assert result.state.steps["repeat"].iteration == 2
