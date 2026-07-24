from __future__ import annotations

from pathlib import Path

import anyio
import pytest

from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.mcp_tools import McpToolService
from gigacode_agent_runtime.web.server import LocalWebServer
from tests.helpers.scheduler import scheduler_config


def test_external_interface_is_rejected_before_bind(tmp_path: Path) -> None:
    tools = McpToolService(scheduler_config(tmp_path))

    with pytest.raises(AgentRuntimeError) as captured:
        LocalWebServer(tools, host="0.0.0.0")

    assert captured.value.code is ErrorCode.CONFIG_INVALID


@pytest.mark.anyio
async def test_server_uses_prebound_localhost_socket(tmp_path: Path) -> None:
    tools = McpToolService(scheduler_config(tmp_path))
    server = LocalWebServer(tools)

    await server.start()
    stream = await anyio.connect_tcp(server.host, server.port)
    await stream.aclose()
    await server.stop()

    assert server.host == "127.0.0.1"
    assert server.port > 0
