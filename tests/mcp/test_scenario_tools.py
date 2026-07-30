from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.mcp_server import create_mcp_server
from gigacode_agent_runtime.mcp_tools import McpToolService
from tests.helpers.scheduler import scheduler_config
from tests.mcp.conftest import write_project_scenario

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_catalog_describe_validate_and_plan(tmp_path: Path) -> None:
    project = tmp_path / "project-scenarios"
    write_project_scenario(project, SCENARIOS / "minimal-valid.yaml")
    tools = McpToolService(
        scheduler_config(tmp_path),
        project_scenarios=project,
    )

    listed = await tools.list_scenarios()
    described = await tools.describe_scenario("minimal-valid")
    validated = await tools.validate_scenario(scenario_name="minimal-valid")
    planned = await tools.plan_scenario(
        scenario_name="minimal-valid",
        inputs={"task": "inspect"},
        workspace=str(tmp_path),
    )

    assert listed["data"]["scenarios"][0]["name"] == "minimal-valid"
    assert described["data"]["agents"]["analyst"]["model"] == "code-model-id"
    assert described["data"]["step_names"] == ["analyze"]
    assert described["data"]["steps"]["analyze"]["kind"] == "agent"
    assert described["data"]["steps"]["analyze"]["needs"] == []
    assert described["data"]["steps"]["analyze"]["output_schema"]["type"] == "object"
    assert described["data"]["result"] == {
        "from": "${steps.analyze.output}",
    }
    assert validated["data"]["valid"] is True
    assert planned["data"]["waves"] == [["analyze"]]


@pytest.mark.anyio
async def test_inline_scenario_validates_and_plans(tmp_path: Path) -> None:
    tools = McpToolService(scheduler_config(tmp_path))
    inline = (SCENARIOS / "sequential-valid.yaml").read_text()

    validated = await tools.validate_scenario(inline_scenario=inline)
    planned = await tools.plan_scenario(
        inline_scenario=inline,
        workspace=str(tmp_path),
    )

    assert validated["ok"] is True
    assert planned["data"]["scenario_name"] == "sequential-valid"


@pytest.mark.anyio
async def test_qwen_wire_contract_accepts_yaml_text_arguments(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project-scenarios"
    write_project_scenario(project, SCENARIOS / "minimal-valid.yaml")
    server = create_mcp_server(
        McpToolService(
            scheduler_config(tmp_path),
            project_scenarios=project,
        )
    )

    _content, planned = await server.call_tool(
        "plan_scenario",
        {
            "scenario_name": "minimal-valid",
            "workspace": str(tmp_path),
            "inputs_yaml": "task: inspect the corporate runtime\n",
        },
    )
    _content, validated = await server.call_tool(
        "validate_scenario",
        {
            "inline_scenario_yaml": (
                SCENARIOS / "sequential-valid.yaml"
            ).read_text(),
        },
    )

    assert planned["ok"] is True
    assert planned["data"]["inputs"] == {
        "task": "inspect the corporate runtime",
    }
    assert validated["data"]["valid"] is True


@pytest.mark.anyio
async def test_qwen_wire_contract_rejects_non_mapping_inputs_yaml(
    tmp_path: Path,
) -> None:
    server = create_mcp_server(McpToolService(scheduler_config(tmp_path)))

    _content, response = await server.call_tool(
        "plan_scenario",
        {
            "scenario_name": "sequential",
            "workspace": str(tmp_path),
            "inputs_yaml": "- not\n- a\n- mapping\n",
        },
    )

    assert response == {
        "ok": False,
        "error": {
            "code": "SCENARIO_INVALID",
            "message": "inputs_yaml must decode to a mapping with string keys",
            "details": {"parameter": "inputs_yaml"},
            "retryable": False,
        },
    }


@pytest.mark.anyio
async def test_qwen_wire_contract_rejects_non_json_yaml_values(
    tmp_path: Path,
) -> None:
    server = create_mcp_server(McpToolService(scheduler_config(tmp_path)))

    _content, response = await server.call_tool(
        "plan_scenario",
        {
            "scenario_name": "sequential",
            "workspace": str(tmp_path),
            "inputs_yaml": "task: 2026-07-30\n",
        },
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "SCENARIO_INVALID"
    assert response["error"]["message"] == (
        "inputs_yaml must contain only JSON-compatible values"
    )


@pytest.mark.anyio
async def test_builtin_placeholder_cannot_be_planned(tmp_path: Path) -> None:
    tools = McpToolService(scheduler_config(tmp_path))

    planned = await tools.plan_scenario(
        scenario_name="sequential",
        inputs={"task": "must configure models first"},
        workspace=str(tmp_path),
    )

    assert planned["ok"] is False
    assert planned["error"]["code"] == "MODEL_NOT_ALLOWED"
    assert planned["error"]["details"]["placeholder"] is True
