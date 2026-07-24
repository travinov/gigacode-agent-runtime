from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.mcp_server import TOOL_NAMES, create_mcp_server
from gigacode_agent_runtime.mcp_tools import McpToolService
from tests.helpers.scheduler import scheduler_config


@pytest.mark.anyio
async def test_discovery_exposes_complete_stable_tool_set(tmp_path: Path) -> None:
    server = create_mcp_server(McpToolService(scheduler_config(tmp_path)))

    tools = await server.list_tools()

    assert [tool.name for tool in tools] == list(TOOL_NAMES)
    schemas = {tool.name: tool.inputSchema for tool in tools}
    assert schemas["start_run"]["required"] == ["workspace"]
    assert schemas["get_run_events"]["properties"]["limit"]["default"] == 100
    assert all(tool.outputSchema is not None for tool in tools)
