from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.domain import RunStatus
from gigacode_agent_runtime.input_gates import InputGateStore
from gigacode_agent_runtime.mcp_tools import McpToolService
from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.state_store import StateStore
from tests.helpers.scheduler import scheduler_adapter, scheduler_config
from tests.mcp.conftest import wait_for_status

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_start_returns_immediately_then_polling_gets_result_and_events(
    tmp_path: Path,
) -> None:
    config = scheduler_config(tmp_path)
    tools = McpToolService(
        config,
        adapter_factory=lambda: scheduler_adapter(tmp_path, "delayed"),
    )
    inline = (SCENARIOS / "parallel-valid.yaml").read_text()

    async with tools:
        started = await tools.start_run(
            inline_scenario=inline,
            inputs={"task": "compare"},
            workspace=str(tmp_path),
            idempotency_key="mcp-request-1",
        )
        repeated = await tools.start_run(
            inline_scenario=inline,
            inputs={"task": "compare"},
            workspace=str(tmp_path),
            idempotency_key="mcp-request-1",
        )
        run_id = started["data"]["run_id"]
        assert repeated["data"]["run_id"] == run_id
        await wait_for_status(tools, run_id, {"completed"})
        result = await tools.get_run_result(run_id)
        first_page = await tools.get_run_events(run_id, limit=2)

    assert result["data"]["result"]["summary"] == "delayed success"
    assert len(first_page["data"]["events"]) == 2
    assert first_page["data"]["has_more"] is True
    assert first_page["data"]["next_cursor"] == 2


@pytest.mark.anyio
async def test_approval_resume_and_cancel_are_process_local_controls(
    tmp_path: Path,
) -> None:
    scenario = """
schema_version: gigacode-agent-runtime/scenario-v1
kind: Scenario
metadata: {name: full-one, title: Full one}
agents:
  worker:
    model: code-model
    permissions: full_access
    system_prompt: Work.
    allowed_tools: [read_file]
steps:
  work:
    kind: agent
    agent: worker
    needs: []
    prompt: {template: Work.}
    output_schema: {type: object}
result:
  from: "${steps.work.output}"
""".lstrip()
    config = scheduler_config(tmp_path, allow_full_access=True)
    tools = McpToolService(
        config,
        adapter_factory=lambda: scheduler_adapter(tmp_path, "success"),
    )

    async with tools:
        started = await tools.start_run(
            inline_scenario=scenario,
            workspace=str(tmp_path),
        )
        run_id = started["data"]["run_id"]
        waiting = await wait_for_status(tools, run_id, {"waiting_for_approval"})
        approved = await tools.approve_run(
            run_id,
            waiting["plan_hash"],
        )
        resumed = await tools.resume_run(run_id)
        completed = await wait_for_status(tools, run_id, {"completed"})

    assert approved["ok"] is True
    assert resumed["ok"] is True
    assert completed["status"] == "completed"


@pytest.mark.anyio
async def test_provide_input_uses_typed_gate_contract(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )
    states = StateStore(config.paths.runs)
    states.transition(prepared.run_id, RunStatus.RUNNING)
    InputGateStore(config.paths.runs, prepared.run_id).request(
        "decision",
        prompt="Approve?",
        input_schema={
            "type": "object",
            "required": ["approved"],
            "properties": {"approved": {"type": "boolean"}},
        },
    )
    tools = McpToolService(config)

    response = await tools.provide_input(
        prepared.run_id,
        "decision",
        {"approved": True},
    )

    assert response["ok"] is True
    assert states.read(prepared.run_id).status.value == "running"


@pytest.mark.anyio
async def test_cancel_stops_active_run(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path)
    tools = McpToolService(
        config,
        adapter_factory=lambda: scheduler_adapter(
            tmp_path,
            "ignore-sigterm",
            graceful_cancel_seconds=0.05,
        ),
    )

    async with tools:
        started = await tools.start_run(
            inline_scenario=(SCENARIOS / "sequential-valid.yaml").read_text(),
            workspace=str(tmp_path),
        )
        run_id = started["data"]["run_id"]
        await wait_for_status(tools, run_id, {"running"})
        cancelled = await tools.cancel_run(run_id)
        state = await wait_for_status(tools, run_id, {"cancelled"})

    assert cancelled["ok"] is True
    assert state["status"] == "cancelled"
