from __future__ import annotations

from pathlib import Path

import pytest

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
