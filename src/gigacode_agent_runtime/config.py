"""Validated global runtime configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import yaml

from .domain import PermissionMode
from .errors import AgentRuntimeError, ErrorCode
from .paths import RuntimePaths, resolve_user_path
from .schema_registry import validate_document
from .version import CONFIG_SCHEMA_VERSION

_DEFAULT_DOCUMENT: dict[str, Any] = {
    "schema_version": CONFIG_SCHEMA_VERSION,
    "runtime": {
        "data_dir": "~/.gigacode/agent-runtime",
        "max_parallel_agents": 4,
        "default_step_timeout_seconds": 900,
        "graceful_cancel_seconds": 10,
        "max_stdout_bytes_per_step": 50 * 1024 * 1024,
        "max_stderr_bytes_per_step": 10 * 1024 * 1024,
    },
    "gigacode": {
        "executable": "auto",
        "model_allowlist": [],
        "environment_allowlist": [
            "PATH",
            "HOME",
            "LANG",
            "LC_ALL",
            "SSL_CERT_FILE",
            "REQUESTS_CA_BUNDLE",
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "NO_PROXY",
        ],
    },
    "permissions": {
        "default": "read_only",
        "allow_full_access": False,
        "require_full_access_confirmation": True,
        "max_parallel_full_access_agents": 1,
        "max_full_access_loop_iterations": 3,
        "trusted_scenario_hashes": {},
    },
    "web": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": "auto",
        "open_automatically": False,
    },
}


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    data_dir: Path
    max_parallel_agents: int
    default_step_timeout_seconds: int
    graceful_cancel_seconds: int
    max_stdout_bytes_per_step: int
    max_stderr_bytes_per_step: int


@dataclass(frozen=True, slots=True)
class GigaCodeSettings:
    executable: str
    model_allowlist: tuple[str, ...]
    environment_allowlist: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PermissionSettings:
    default: PermissionMode
    allow_full_access: bool
    require_full_access_confirmation: bool
    max_parallel_full_access_agents: int
    max_full_access_loop_iterations: int
    trusted_scenario_hashes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class WebSettings:
    enabled: bool
    host: str
    port: int | None
    open_automatically: bool


@dataclass(frozen=True, slots=True)
class EffectiveConfig:
    schema_version: str
    source_path: Path
    paths: RuntimePaths
    runtime: RuntimeSettings
    gigacode: GigaCodeSettings
    permissions: PermissionSettings
    web: WebSettings

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runtime": {
                "data_dir": str(self.runtime.data_dir),
                "max_parallel_agents": self.runtime.max_parallel_agents,
                "default_step_timeout_seconds": self.runtime.default_step_timeout_seconds,
                "graceful_cancel_seconds": self.runtime.graceful_cancel_seconds,
                "max_stdout_bytes_per_step": self.runtime.max_stdout_bytes_per_step,
                "max_stderr_bytes_per_step": self.runtime.max_stderr_bytes_per_step,
            },
            "gigacode": {
                "executable": self.gigacode.executable,
                "model_allowlist": list(self.gigacode.model_allowlist),
                "environment_allowlist": list(self.gigacode.environment_allowlist),
            },
            "permissions": {
                "default": self.permissions.default.value,
                "allow_full_access": self.permissions.allow_full_access,
                "require_full_access_confirmation": (
                    self.permissions.require_full_access_confirmation
                ),
                "max_parallel_full_access_agents": (
                    self.permissions.max_parallel_full_access_agents
                ),
                "max_full_access_loop_iterations": (
                    self.permissions.max_full_access_loop_iterations
                ),
                "trusted_scenario_hashes": dict(self.permissions.trusted_scenario_hashes),
            },
            "web": {
                "enabled": self.web.enabled,
                "host": self.web.host,
                "port": self.web.port if self.web.port is not None else "auto",
                "open_automatically": self.web.open_automatically,
            },
        }


def _merge_dicts(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(cast(dict[str, Any], merged[key]), value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": CONFIG_SCHEMA_VERSION}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AgentRuntimeError(
            ErrorCode.CONFIG_INVALID,
            f"Cannot read runtime configuration: {path}",
            details={"path": str(path)},
        ) from exc
    if not isinstance(loaded, dict):
        raise AgentRuntimeError(
            ErrorCode.CONFIG_INVALID,
            "Runtime configuration must be a YAML/JSON object",
            details={"path": "/"},
        )
    return cast(dict[str, Any], loaded)


def load_config(
    path: Path | None = None,
    *,
    home: Path | None = None,
) -> EffectiveConfig:
    resolved_home = (home or Path(os.path.expanduser("~"))).resolve(strict=False)
    default_paths = RuntimePaths.for_home(resolved_home)
    source_path = (path or default_paths.config_file).resolve(strict=False)
    raw = _read_config(source_path)
    validate_document("config-v1", raw)
    document = _merge_dicts(_DEFAULT_DOCUMENT, raw)

    runtime_raw = cast(dict[str, Any], document["runtime"])
    gigacode_raw = cast(dict[str, Any], document["gigacode"])
    permissions_raw = cast(dict[str, Any], document["permissions"])
    web_raw = cast(dict[str, Any], document["web"])

    data_dir = resolve_user_path(str(runtime_raw["data_dir"]), resolved_home)
    paths = default_paths.with_data_dir(data_dir)
    max_parallel_agents = int(runtime_raw["max_parallel_agents"])
    max_parallel_full_access = int(permissions_raw["max_parallel_full_access_agents"])
    if max_parallel_full_access > max_parallel_agents:
        raise AgentRuntimeError(
            ErrorCode.CONFIG_INVALID,
            "max_parallel_full_access_agents cannot exceed max_parallel_agents",
            details={"path": "/permissions/max_parallel_full_access_agents"},
        )

    port_value = web_raw["port"]
    port = None if port_value == "auto" else int(port_value)
    trusted = MappingProxyType(
        {
            str(name): str(value)
            for name, value in permissions_raw["trusted_scenario_hashes"].items()
        }
    )

    return EffectiveConfig(
        schema_version=str(document["schema_version"]),
        source_path=source_path,
        paths=paths,
        runtime=RuntimeSettings(
            data_dir=data_dir,
            max_parallel_agents=max_parallel_agents,
            default_step_timeout_seconds=int(runtime_raw["default_step_timeout_seconds"]),
            graceful_cancel_seconds=int(runtime_raw["graceful_cancel_seconds"]),
            max_stdout_bytes_per_step=int(runtime_raw["max_stdout_bytes_per_step"]),
            max_stderr_bytes_per_step=int(runtime_raw["max_stderr_bytes_per_step"]),
        ),
        gigacode=GigaCodeSettings(
            executable=str(gigacode_raw["executable"]),
            model_allowlist=tuple(str(item) for item in gigacode_raw["model_allowlist"]),
            environment_allowlist=tuple(
                str(item) for item in gigacode_raw["environment_allowlist"]
            ),
        ),
        permissions=PermissionSettings(
            default=PermissionMode(str(permissions_raw["default"])),
            allow_full_access=bool(permissions_raw["allow_full_access"]),
            require_full_access_confirmation=bool(
                permissions_raw["require_full_access_confirmation"]
            ),
            max_parallel_full_access_agents=max_parallel_full_access,
            max_full_access_loop_iterations=int(
                permissions_raw["max_full_access_loop_iterations"]
            ),
            trusted_scenario_hashes=trusted,
        ),
        web=WebSettings(
            enabled=bool(web_raw["enabled"]),
            host=str(web_raw["host"]),
            port=port,
            open_automatically=bool(web_raw["open_automatically"]),
        ),
    )
