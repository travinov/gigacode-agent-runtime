from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.domain import PermissionMode
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode

FIXTURES = Path(__file__).parents[1] / "fixtures" / "config"


def test_missing_config_returns_safe_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.yaml", home=tmp_path / "home")

    assert config.runtime.max_parallel_agents == 4
    assert config.permissions.default is PermissionMode.READ_ONLY
    assert config.permissions.allow_full_access is False
    assert config.permissions.max_parallel_full_access_agents == 1
    assert config.web.host == "127.0.0.1"
    assert config.web.open_automatically is False


def test_full_config_is_loaded_without_using_real_home(tmp_path: Path) -> None:
    config = load_config(FIXTURES / "full.yaml", home=tmp_path / "home")

    assert config.runtime.data_dir == tmp_path / "home" / "custom-runtime"
    assert config.runtime.max_parallel_agents == 6
    assert config.gigacode.executable == "/opt/corporate/bin/gigacode"
    assert config.gigacode.model_allowlist == ("code-model-id", "review-model-id")
    assert config.permissions.default is PermissionMode.PROPOSE_ONLY
    assert config.permissions.allow_full_access is True
    assert config.web.port == 8765


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "schema_version: gigacode-agent-runtime/config-v1\nruntime:\n  surprise: true\n"
    )

    with pytest.raises(AgentRuntimeError) as captured:
        load_config(path, home=tmp_path)

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert captured.value.details["path"] == "/runtime"


def test_invalid_limit_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "schema_version: gigacode-agent-runtime/config-v1\n"
        "runtime:\n  max_parallel_agents: 0\n"
    )

    with pytest.raises(AgentRuntimeError) as captured:
        load_config(path, home=tmp_path)

    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_non_loopback_web_host_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "schema_version: gigacode-agent-runtime/config-v1\nweb:\n  host: 0.0.0.0\n"
    )

    with pytest.raises(AgentRuntimeError) as captured:
        load_config(path, home=tmp_path)

    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_snapshot_contains_environment_names_not_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "https://secret-proxy.example")
    config = load_config(FIXTURES / "full.yaml", home=tmp_path)

    snapshot = config.to_snapshot()

    assert snapshot["gigacode"]["environment_allowlist"] == ["PATH", "HOME", "HTTPS_PROXY"]
    assert "secret-proxy.example" not in repr(snapshot)
