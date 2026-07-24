from __future__ import annotations

from pathlib import Path

import httpx

from gigacode_agent_runtime.mcp_tools import McpToolService
from gigacode_agent_runtime.web.auth import DashboardAuth
from gigacode_agent_runtime.web.server import create_dashboard_app
from tests.helpers.scheduler import scheduler_config


def dashboard_fixture(tmp_path: Path):
    tools = McpToolService(scheduler_config(tmp_path))
    auth = DashboardAuth()
    app = create_dashboard_app(tools, auth)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
    )
    return tools, auth, client


async def authenticate(client: httpx.AsyncClient, auth: DashboardAuth) -> str:
    response = await client.post(
        "/api/bootstrap",
        json={"token": auth.bootstrap_token},
    )
    assert response.status_code == 200
    return str(response.json()["data"]["csrf_token"])
