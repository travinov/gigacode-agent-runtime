from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.mcp_tools import McpToolService
from gigacode_agent_runtime.studio import StudioService
from gigacode_agent_runtime.web.auth import (
    SESSION_COOKIE,
    STUDIO_SESSION_COOKIE,
    DashboardAuth,
)
from gigacode_agent_runtime.web.server import create_dashboard_app
from gigacode_agent_runtime.web.studio_server import (
    LocalStudioServer,
    create_studio_app,
)


def _studio_fixture(tmp_path: Path):
    home = tmp_path / "home"
    config_path = home / ".gigacode" / "agent-runtime" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "schema_version: gigacode-agent-runtime/config-v1\n"
        "gigacode:\n  model_allowlist: [code-model-id]\n",
        encoding="utf-8",
    )
    config = load_config(config_path, home=home)
    service = StudioService(
        config,
        project_scenarios=tmp_path / "workspace" / ".gigacode" / "scenarios",
    )
    auth = DashboardAuth(surface_name="Studio")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_studio_app(service, auth)),
        base_url="http://127.0.0.1",
    )
    return config, service, auth, client


async def _authenticate(client: httpx.AsyncClient, auth: DashboardAuth) -> str:
    response = await client.post(
        "/api/bootstrap",
        json={"token": auth.bootstrap_token},
    )
    assert response.status_code == 200
    return str(response.json()["data"]["csrf_token"])


def _agent_draft(name: str = "reviewer") -> dict[str, object]:
    return {
        "kind": "agent",
        "scope": "user",
        "name": name,
        "document": {
            "name": name,
            "description": "Reviews changes.",
            "model": "code-model-id",
            "approvalMode": "plan",
            "tools": ["read_file"],
            "disallowedTools": [],
            "system_prompt": "Review the proposed change.",
        },
    }


@pytest.mark.anyio
async def test_studio_auth_is_separate_from_dashboard(tmp_path: Path) -> None:
    config, _service, studio_auth, studio_client = _studio_fixture(tmp_path)
    dashboard_auth = DashboardAuth()
    dashboard_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_dashboard_app(McpToolService(config), dashboard_auth)
        ),
        base_url="http://127.0.0.1",
    )
    try:
        dashboard_response = await dashboard_client.post(
            "/api/bootstrap",
            json={"token": dashboard_auth.bootstrap_token},
        )
        studio_response = await studio_client.post(
            "/api/bootstrap",
            json={"token": studio_auth.bootstrap_token},
        )
        foreign_token = await studio_client.post(
            "/api/bootstrap",
            json={"token": dashboard_auth.bootstrap_token},
        )
    finally:
        await dashboard_client.aclose()
        await studio_client.aclose()

    assert dashboard_response.status_code == 200
    assert studio_response.status_code == 200
    assert foreign_token.status_code == 403
    assert f"{SESSION_COOKIE}=" in dashboard_response.headers["set-cookie"]
    assert f"{STUDIO_SESSION_COOKIE}=" in studio_response.headers["set-cookie"]
    assert STUDIO_SESSION_COOKIE not in dashboard_response.headers["set-cookie"]


@pytest.mark.anyio
async def test_studio_session_endpoint_supports_refresh_without_bootstrap_token(
    tmp_path: Path,
) -> None:
    _config, _service, auth, client = _studio_fixture(tmp_path)
    try:
        missing = await client.get("/api/session")
        csrf = await _authenticate(client, auth)
        refreshed = await client.get("/api/session")
    finally:
        await client.aclose()

    assert missing.status_code == 403
    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["csrf_token"] == csrf


@pytest.mark.anyio
async def test_studio_catalog_detail_preview_and_one_shot_apply(tmp_path: Path) -> None:
    _config, service, auth, client = _studio_fixture(tmp_path)
    try:
        unauthorized = await client.get("/api/studio/catalog")
        csrf = await _authenticate(client, auth)
        catalog = await client.get("/api/studio/catalog")
        detail = await client.get("/api/studio/resources/config/selected")
        missing_csrf = await client.post(
            "/api/studio/preview",
            json=_agent_draft(),
        )
        preview = await client.post(
            "/api/studio/preview",
            json=_agent_draft(),
            headers={"X-CSRF-Token": csrf},
        )
        preview_id = preview.json()["data"]["preview_id"]
        applied = await client.post(
            "/api/studio/apply",
            json={"preview_id": preview_id},
            headers={"X-CSRF-Token": csrf},
        )
        replayed = await client.post(
            "/api/studio/apply",
            json={"preview_id": preview_id},
            headers={"X-CSRF-Token": csrf},
        )
    finally:
        await client.aclose()

    assert unauthorized.status_code == 403
    assert catalog.status_code == 200
    assert catalog.json()["data"]["paths"]["home"] == str(service.config.paths.home)
    assert detail.json()["data"]["kind"] == "config"
    assert missing_csrf.status_code == 403
    assert preview.status_code == 200
    assert applied.status_code == 200
    assert Path(applied.json()["data"]["target_path"]).exists()
    assert replayed.status_code == 400
    assert replayed.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


@pytest.mark.anyio
async def test_studio_apply_returns_conflict_after_external_edit(tmp_path: Path) -> None:
    _config, _service, auth, client = _studio_fixture(tmp_path)
    try:
        csrf = await _authenticate(client, auth)
        preview = await client.post(
            "/api/studio/preview",
            json=_agent_draft(),
            headers={"X-CSRF-Token": csrf},
        )
        data = preview.json()["data"]
        target = Path(data["target_path"])
        target.parent.mkdir(parents=True)
        target.write_text("external edit\n", encoding="utf-8")
        applied = await client.post(
            "/api/studio/apply",
            json={"preview_id": data["preview_id"]},
            headers={"X-CSRF-Token": csrf},
        )
    finally:
        await client.aclose()

    assert applied.status_code == 409
    assert applied.json()["error"]["code"] == "PLAN_CONFLICT"
    assert target.read_text(encoding="utf-8") == "external edit\n"


def test_studio_rejects_external_bind(tmp_path: Path) -> None:
    _config, service, _auth, _client = _studio_fixture(tmp_path)

    with pytest.raises(AgentRuntimeError) as captured:
        LocalStudioServer(service, host="0.0.0.0")

    assert captured.value.code is ErrorCode.CONFIG_INVALID
