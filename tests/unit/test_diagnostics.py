from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.adapter_factory import create_gigacode_adapter
from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.diagnostics import diagnose_runtime
from tests.helpers.scheduler import scheduler_adapter, scheduler_config


def _checks(report: dict[str, object]) -> dict[str, dict[str, object]]:
    raw_checks = report["checks"]
    assert isinstance(raw_checks, list)
    return {
        str(check["code"]): check
        for check in raw_checks
        if isinstance(check, dict)
    }


@pytest.mark.anyio
async def test_diagnostics_have_stable_statuses_without_llm_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    config = scheduler_config(tmp_path)

    report = await diagnose_runtime(
        config,
        lambda: scheduler_adapter(tmp_path, "success"),
    )
    checks = _checks(report)

    assert report["status"] == "warning"
    assert checks["platform_supported"]["status"] == "ok"
    assert checks["gigacode_capabilities_available"]["status"] == "ok"
    assert checks["model_allowlist_empty"]["status"] == "warning"
    assert checks["agent_catalog_empty"]["status"] == "warning"
    assert checks["subprocess_smoke_not_requested"]["status"] == "ok"


@pytest.mark.anyio
async def test_missing_gigacode_is_typed_error_not_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    config_path = tmp_path / "runtime.yaml"
    config_path.write_text(
        "schema_version: gigacode-agent-runtime/config-v1\n"
        "gigacode:\n"
        f"  executable: {tmp_path / 'missing-gigacode'}\n"
    )
    config = load_config(config_path, home=tmp_path / "home")

    report = await diagnose_runtime(
        config,
        lambda: create_gigacode_adapter(config),
    )
    check = _checks(report)["gigacode_unavailable"]

    assert report["status"] == "error"
    assert check["status"] == "error"
    assert "Traceback" not in str(check)


@pytest.mark.anyio
async def test_unsupported_platform_and_full_access_are_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    config = scheduler_config(tmp_path, allow_full_access=True)

    report = await diagnose_runtime(
        config,
        lambda: scheduler_adapter(tmp_path, "success"),
    )
    checks = _checks(report)

    assert checks["platform_unsupported"]["status"] == "error"
    assert checks["full_access_enabled"]["status"] == "warning"


@pytest.mark.anyio
async def test_opt_in_zero_data_subprocess_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    config = scheduler_config(tmp_path)

    report = await diagnose_runtime(
        config,
        lambda: scheduler_adapter(tmp_path, "success"),
        subprocess_smoke=True,
    )

    assert _checks(report)["subprocess_smoke_passed"]["status"] == "ok"


@pytest.mark.anyio
async def test_diagnostics_validate_reusable_agent_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    agents = tmp_path / "home" / ".gigacode" / "agents"
    agents.mkdir(parents=True)
    (agents / "analyst.md").write_text(
        "---\n"
        "name: reusable-analyst\n"
        "description: Reusable analyst.\n"
        "---\n\n"
        "Analyze requirements.\n"
    )
    config = scheduler_config(tmp_path)

    report = await diagnose_runtime(
        config,
        lambda: scheduler_adapter(tmp_path, "success"),
    )

    check = _checks(report)["agent_catalog_available"]
    assert check["status"] == "ok"
    assert check["details"]["agents"] == ["reusable-analyst"]
