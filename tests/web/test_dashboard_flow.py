from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.mcp_tools import McpToolService
from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from tests.helpers.scheduler import scheduler_config
from tests.web.conftest import authenticate, dashboard_fixture

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_browserless_dashboard_lists_run_and_executes_control(
    tmp_path: Path,
) -> None:
    tools, auth, client = dashboard_fixture(tmp_path)
    prepared = RuntimeService(tools.config).start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )
    csrf = await authenticate(client, auth)
    try:
        listed = await client.get("/api/runs")
        controlled = await client.post(
            f"/api/runs/{prepared.run_id}/cancel",
            json={},
            headers={"X-CSRF-Token": csrf},
        )
        status = await client.get(f"/api/runs/{prepared.run_id}")
    finally:
        await client.aclose()

    assert listed.json()["data"]["runs"][0]["run_id"] == prepared.run_id
    assert controlled.status_code == 200
    assert status.json()["data"]["status"] == "cancelled"


@pytest.mark.anyio
async def test_open_dashboard_is_lazy_and_returns_fragment_token(
    tmp_path: Path,
) -> None:
    tools = McpToolService(scheduler_config(tmp_path))

    async with tools:
        response = await tools.open_dashboard()

    url = response["data"]["url"]
    assert url.startswith("http://127.0.0.1:")
    assert "/#token=" in url
