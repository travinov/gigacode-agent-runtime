from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.mcp_tools import McpToolService
from tests.helpers.scheduler import scheduler_config


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.anyio
async def test_open_studio_is_lazy_authenticated_and_non_mutating(
    tmp_path: Path,
) -> None:
    config = scheduler_config(tmp_path)
    tools = McpToolService(
        config,
        project_scenarios=tmp_path / "workspace" / ".gigacode" / "scenarios",
    )
    before = _snapshot(tmp_path)

    async with tools:
        response = await tools.open_studio(open_browser=False)
        during = _snapshot(tmp_path)

    assert response["ok"] is True
    url = str(response["data"]["url"])
    assert url.startswith("http://127.0.0.1:")
    assert "/#token=" in url
    assert response["data"]["browser_opened"] is False
    assert during == before


@pytest.mark.anyio
async def test_dashboard_and_studio_servers_coexist_on_distinct_ports(
    tmp_path: Path,
) -> None:
    tools = McpToolService(scheduler_config(tmp_path))

    async with tools:
        dashboard = await tools.open_dashboard()
        studio = await tools.open_studio(open_browser=False)

    dashboard_url = str(dashboard["data"]["url"])
    studio_url = str(studio["data"]["url"])
    assert dashboard["ok"] is True and studio["ok"] is True
    assert dashboard_url != studio_url
    assert dashboard_url.split(":")[2].split("/")[0] != (studio_url.split(":")[2].split("/")[0])


@pytest.mark.anyio
async def test_injected_open_studio_url_keeps_tool_side_effect_free(
    tmp_path: Path,
) -> None:
    calls = 0

    def studio_url() -> str:
        nonlocal calls
        calls += 1
        return "http://127.0.0.1:43210/#token=test"

    tools = McpToolService(
        scheduler_config(tmp_path),
        studio_url=studio_url,
    )
    async with tools:
        response = await tools.open_studio(open_browser=False)

    assert calls == 1
    assert response == {
        "ok": True,
        "data": {
            "url": "http://127.0.0.1:43210/#token=test",
            "browser_opened": False,
        },
    }


@pytest.mark.anyio
async def test_open_studio_opens_exact_fragment_url_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []

    def open_browser(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(
        "gigacode_agent_runtime.mcp_tools.webbrowser.open",
        open_browser,
    )
    tools = McpToolService(scheduler_config(tmp_path))

    async with tools:
        response = await tools.open_studio()

    url = str(response["data"]["url"])
    assert opened == [url]
    assert "/#token=" in url
    assert response["data"]["browser_opened"] is True
