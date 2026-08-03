from __future__ import annotations

import json
from pathlib import Path

import pytest

from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from tests.web.conftest import authenticate, dashboard_fixture

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_mutation_requires_csrf_and_api_has_no_source_paths_or_secrets(
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
        status = await client.get(f"/api/runs/{prepared.run_id}")
        plan = await client.get(f"/api/runs/{prepared.run_id}/plan")
        denied = await client.post(f"/api/runs/{prepared.run_id}/cancel", json={})
        accepted = await client.post(
            f"/api/runs/{prepared.run_id}/cancel",
            json={},
            headers={"X-CSRF-Token": csrf},
        )
    finally:
        await client.aclose()

    rendered = json.dumps(
        {"status": status.json(), "plan": plan.json()},
        ensure_ascii=False,
    )
    assert status.status_code == 200
    assert plan.status_code == 200
    assert denied.status_code == 403
    assert accepted.status_code == 200
    assert str(SCENARIOS) not in rendered
    assert "FAKE_GIGACODE_PROFILE" not in rendered
    assert "source" not in plan.json()["data"]
    assert "workspace" not in plan.json()["data"]


@pytest.mark.anyio
async def test_artifact_pagination_rejects_traversal_like_cursor(
    tmp_path: Path,
) -> None:
    tools, auth, client = dashboard_fixture(tmp_path)
    prepared = RuntimeService(tools.config).start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )
    await authenticate(client, auth)
    try:
        response = await client.get(
            f"/api/runs/{prepared.run_id}/artifacts?after=-1"
        )
        traversal = await client.get("/assets/../pyproject.toml")
    finally:
        await client.aclose()

    assert response.status_code == 400
    assert traversal.status_code == 404
