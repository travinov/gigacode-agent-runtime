from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.scheduler import DagScheduler
from tests.helpers.scheduler import agent_traces, scheduler_adapter, scheduler_config


def _scenario(path: Path) -> Path:
    path.write_text(
        """
schema_version: gigacode-agent-runtime/scenario-v1
kind: Scenario
metadata:
  name: review-repair
  title: Review and repair
agents:
  reviewer:
    model: review-model
    permissions: read_only
    system_prompt: Review.
  creator:
    model: code-model
    permissions: propose_only
    system_prompt: Repair.
steps:
  improve:
    kind: loop
    needs: []
    max_iterations: 4
    timeout_seconds: 30
    on_limit: fail
    body:
      steps:
        review:
          kind: agent
          agent: reviewer
          needs: []
          prompt: {template: "Review iteration ${loop.iteration}."}
          output_schema:
            type: object
            required: [approved]
            properties:
              approved: {type: boolean}
              feedback: {type: string}
        repair:
          kind: agent
          agent: creator
          needs: [review]
          when:
            ref: "${loop.steps.review.output.approved}"
            op: eq
            value: false
          prompt:
            template: "Repair: ${loop.steps.review.output.feedback}"
          output_schema: {type: object}
    until:
      ref: "${loop.steps.review.output.approved}"
      op: eq
      value: true
result:
  from: "${steps.improve.output}"
""".lstrip()
    )
    return path


@pytest.mark.anyio
async def test_approved_first_review_skips_repair(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(_scenario(tmp_path / "scenario.yaml")),
        inputs={},
        workspace=tmp_path,
    )

    result = await DagScheduler(config, scheduler_adapter(tmp_path, "success")).run(
        prepared
    )

    assert result.state.status.value == "completed"
    assert result.state.steps["improve"].iteration == 1
    assert "repair@iteration-1" not in result.state.steps
    assert len(agent_traces(tmp_path)) == 1


@pytest.mark.anyio
async def test_review_repair_reaches_approval_on_second_iteration(
    tmp_path: Path,
) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(_scenario(tmp_path / "scenario.yaml")),
        inputs={},
        workspace=tmp_path,
    )

    result = await DagScheduler(
        config,
        scheduler_adapter(tmp_path, "review-repair"),
    ).run(prepared)

    assert result.state.status.value == "completed"
    assert result.state.steps["improve"].iteration == 2
    assert result.state.steps["review@iteration-1"].status.value == "completed"
    assert result.state.steps["repair@iteration-1"].status.value == "completed"
    assert result.state.steps["review@iteration-2"].status.value == "completed"
    assert "repair@iteration-2" not in result.state.steps
    assert len(agent_traces(tmp_path)) == 3


@pytest.mark.anyio
async def test_independent_loop_nodes_run_in_parallel(tmp_path: Path) -> None:
    scenario_path = tmp_path / "parallel-loops.yaml"
    scenario_path.write_text(
        """
schema_version: gigacode-agent-runtime/scenario-v1
kind: Scenario
metadata:
  name: parallel-loops
  title: Parallel loops
agents:
  worker:
    model: code-model
    permissions: read_only
    system_prompt: Work.
steps:
  first:
    kind: loop
    needs: []
    max_iterations: 1
    timeout_seconds: 30
    on_limit: fail
    body:
      steps:
        work_a:
          kind: agent
          agent: worker
          needs: []
          prompt: {template: First.}
          output_schema: {type: object}
    until:
      ref: "${loop.steps.work_a.output.summary}"
      op: eq
      value: delayed success
  second:
    kind: loop
    needs: []
    max_iterations: 1
    timeout_seconds: 30
    on_limit: fail
    body:
      steps:
        work_b:
          kind: agent
          agent: worker
          needs: []
          prompt: {template: Second.}
          output_schema: {type: object}
    until:
      ref: "${loop.steps.work_b.output.summary}"
      op: eq
      value: delayed success
result:
  from: "${steps.second.output}"
""".lstrip()
    )
    config = scheduler_config(tmp_path, max_parallel=2)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(scenario_path),
        inputs={},
        workspace=tmp_path,
    )

    result = await DagScheduler(config, scheduler_adapter(tmp_path, "delayed")).run(
        prepared
    )
    traces = sorted(agent_traces(tmp_path), key=lambda trace: trace["start_monotonic"])

    assert result.state.status.value == "completed"
    assert len(traces) == 2
    assert traces[1]["start_monotonic"] < traces[0]["end_monotonic"]
