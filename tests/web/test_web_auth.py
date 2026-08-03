from __future__ import annotations

from pathlib import Path

import pytest

from tests.web.conftest import authenticate, dashboard_fixture


@pytest.mark.anyio
async def test_bootstrap_is_one_time_and_cookie_is_hardened(tmp_path: Path) -> None:
    _tools, auth, client = dashboard_fixture(tmp_path)
    try:
        invalid = await client.post("/api/bootstrap", json={"token": "wrong"})
        response = await client.post(
            "/api/bootstrap",
            json={"token": auth.bootstrap_token},
        )
        repeated = await client.post(
            "/api/bootstrap",
            json={"token": auth.bootstrap_token},
        )
    finally:
        await client.aclose()

    cookie = response.headers["set-cookie"].lower()
    assert invalid.status_code == 403
    assert response.status_code == 200
    assert repeated.status_code == 403
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie


@pytest.mark.anyio
async def test_security_headers_and_authenticated_api(tmp_path: Path) -> None:
    _tools, auth, client = dashboard_fixture(tmp_path)
    try:
        index = await client.get("/")
        unauthorized = await client.get("/api/runs")
        await authenticate(client, auth)
        authorized = await client.get("/api/runs")
    finally:
        await client.aclose()

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200
    assert "script-src 'self'" in index.headers["content-security-policy"]
    assert "'unsafe-inline'" not in index.headers["content-security-policy"]
    assert index.headers["x-content-type-options"] == "nosniff"
    assert index.headers["referrer-policy"] == "no-referrer"
