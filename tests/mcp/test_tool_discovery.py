from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.mcp_server import (
    TOOL_DESCRIPTIONS,
    TOOL_NAMES,
    create_mcp_server,
)
from gigacode_agent_runtime.mcp_tools import McpToolService
from tests.helpers.scheduler import scheduler_config


@pytest.mark.anyio
async def test_discovery_exposes_complete_stable_tool_set(tmp_path: Path) -> None:
    server = create_mcp_server(McpToolService(scheduler_config(tmp_path)))

    tools = await server.list_tools()

    assert [tool.name for tool in tools] == list(TOOL_NAMES)
    assert {tool.name: tool.description for tool in tools} == TOOL_DESCRIPTIONS
    assert all(tool.name and tool.description for tool in tools)
    schemas = {tool.name: tool.inputSchema for tool in tools}
    assert schemas["start_run"]["required"] == ["workspace"]
    assert "inputs" not in schemas["plan_scenario"]["properties"]
    assert "inline_scenario" not in schemas["plan_scenario"]["properties"]
    assert schemas["plan_scenario"]["properties"]["inputs_yaml"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert (
        "YAML mapping text"
        in schemas["plan_scenario"]["properties"]["inputs_yaml"]["description"]
    )
    assert "inline_scenario_yaml" in schemas["validate_scenario"]["properties"]
    assert schemas["describe_agent_profile"]["required"] == ["agent_name"]
    assert "GigaCode agent" in (
        schemas["describe_agent_profile"]["properties"]["agent_name"]["description"]
    )
    assert schemas["get_run_events"]["properties"]["limit"]["default"] == 100
    assert all(tool.outputSchema is not None for tool in tools)
