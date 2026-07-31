"""Safe, structured runtime diagnostics without an LLM request."""

from __future__ import annotations

import importlib.metadata
import os
import platform
import socket
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from .adapters.capabilities import GigaCodeCapabilities
from .config import EffectiveConfig
from .domain import PermissionMode
from .errors import AgentRuntimeError
from .process_supervisor import ProcessSupervisor
from .version import (
    CONFIG_SCHEMA_VERSION,
    EXECUTION_PLAN_SCHEMA_VERSION,
    RUN_EVENT_SCHEMA_VERSION,
    RUN_STATE_SCHEMA_VERSION,
    SCENARIO_SCHEMA_VERSION,
    __version__,
)

DiagnosticStatus = Literal["ok", "warning", "error"]


class CapabilityProbe(Protocol):
    async def detect_capabilities(self) -> GigaCodeCapabilities: ...


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    status: DiagnosticStatus
    code: str
    message: str
    remediation: str | None = None
    details: Mapping[str, object] | None = None

    def to_document(self) -> dict[str, object]:
        return {
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
            "details": dict(self.details or {}),
        }


def _overall_status(checks: list[DiagnosticCheck]) -> DiagnosticStatus:
    statuses = {check.status for check in checks}
    if "error" in statuses:
        return "error"
    if "warning" in statuses:
        return "warning"
    return "ok"


def _os_check() -> DiagnosticCheck:
    system = platform.system()
    machine = platform.machine()
    details = {"os": system, "architecture": machine}
    if system != "Darwin":
        return DiagnosticCheck(
            "error",
            "platform_unsupported",
            "Runtime v1 supports macOS only",
            "Use a macOS x86_64 host for the v1 corporate release.",
            details,
        )
    if machine not in {"x86_64", "AMD64"}:
        return DiagnosticCheck(
            "warning",
            "architecture_not_release_target",
            "This macOS architecture is not the v1 corporate release target",
            "Perform release acceptance on macOS x86_64.",
            details,
        )
    return DiagnosticCheck(
        "ok",
        "platform_supported",
        "Operating system and architecture are supported",
        details=details,
    )


def _python_check() -> DiagnosticCheck:
    version = ".".join(str(part) for part in sys.version_info[:3])
    supported = (3, 11) <= sys.version_info[:2] < (3, 15)
    return DiagnosticCheck(
        "ok" if supported else "error",
        "python_supported" if supported else "python_unsupported",
        (
            f"Python {version} is supported"
            if supported
            else f"Python {version} is outside the supported range"
        ),
        None if supported else "Install Python 3.11, 3.12, 3.13, or 3.14.",
        {"python": version, "executable": sys.executable},
    )


def _version_check() -> DiagnosticCheck:
    return DiagnosticCheck(
        "ok",
        "runtime_contract_versions",
        "Runtime and persisted contract versions are available",
        details={
            "runtime_version": __version__,
            "schemas": {
                "config": CONFIG_SCHEMA_VERSION,
                "scenario": SCENARIO_SCHEMA_VERSION,
                "execution_plan": EXECUTION_PLAN_SCHEMA_VERSION,
                "run_state": RUN_STATE_SCHEMA_VERSION,
                "run_event": RUN_EVENT_SCHEMA_VERSION,
            },
        },
    )


def _mcp_sdk_check() -> DiagnosticCheck:
    try:
        version = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        return DiagnosticCheck(
            "error",
            "mcp_sdk_missing",
            "MCP SDK is not installed in the runtime environment",
            "Reinstall the runtime from the complete offline ZIP.",
        )
    return DiagnosticCheck(
        "ok",
        "mcp_sdk_available",
        f"MCP SDK {version} is available",
        details={"version": version},
    )


def _nearest_existing(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _directory_check(config: EffectiveConfig) -> DiagnosticCheck:
    paths = (
        config.runtime.data_dir,
        config.paths.runs,
        config.paths.user_scenarios,
        config.source_path.parent,
    )
    failures: list[str] = []
    for path in paths:
        probe = path if path.exists() else _nearest_existing(path)
        if (path.exists() and not path.is_dir()) or not (
            probe.is_dir() and os.access(probe, os.W_OK | os.X_OK)
        ):
            failures.append(str(path))
    if failures:
        return DiagnosticCheck(
            "error",
            "runtime_directories_unwritable",
            "One or more runtime directories cannot be created or written",
            "Grant the current user write access or choose another runtime.data_dir.",
            {"paths": failures},
        )
    return DiagnosticCheck(
        "ok",
        "runtime_directories_writable",
        "Runtime, state, scenario, and configuration directories are writable",
    )


def _web_bind_check(config: EffectiveConfig) -> DiagnosticCheck:
    if not config.web.enabled:
        return DiagnosticCheck(
            "ok",
            "web_ui_disabled",
            "Local Web UI is disabled by configuration",
        )
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((config.web.host, config.web.port or 0))
    except OSError as exc:
        return DiagnosticCheck(
            "error",
            "web_bind_failed",
            "Local Web UI address cannot be bound",
            "Free the configured port or set web.port to auto.",
            {"host": config.web.host, "port": config.web.port, "errno": exc.errno},
        )
    finally:
        probe.close()
    return DiagnosticCheck(
        "ok",
        "web_bind_available",
        "Local Web UI can bind to loopback",
        details={"host": config.web.host, "port": config.web.port or "auto"},
    )


def _model_allowlist_check(config: EffectiveConfig) -> DiagnosticCheck:
    models = list(config.gigacode.model_allowlist)
    if not models:
        return DiagnosticCheck(
            "warning",
            "model_allowlist_empty",
            "Model allowlist is empty, so scenario model IDs are unrestricted",
            "Add approved corporate model IDs to gigacode.model_allowlist.",
            {"count": 0},
        )
    return DiagnosticCheck(
        "ok",
        "model_allowlist_configured",
        f"Model allowlist contains {len(models)} entries",
        details={"models": models},
    )


def _permission_check(config: EffectiveConfig) -> DiagnosticCheck:
    permissions = config.permissions
    dangerous = (
        permissions.allow_full_access
        or permissions.default is PermissionMode.FULL_ACCESS
    )
    if dangerous and not permissions.require_full_access_confirmation:
        return DiagnosticCheck(
            "error",
            "full_access_confirmation_disabled",
            "Full access is enabled without per-plan confirmation",
            "Set permissions.require_full_access_confirmation to true.",
            {
                "allow_full_access": permissions.allow_full_access,
                "default": permissions.default.value,
            },
        )
    if dangerous:
        return DiagnosticCheck(
            "warning",
            "full_access_enabled",
            "Full access is enabled and requires exact-plan confirmation",
            "Keep the allowlist and trusted plan hashes narrowly scoped.",
            {
                "allow_full_access": permissions.allow_full_access,
                "default": permissions.default.value,
                "confirmation_required": True,
            },
        )
    return DiagnosticCheck(
        "ok",
        "full_access_disabled",
        "Full access is disabled",
    )


async def _capabilities_check(
    adapter_factory: Callable[[], CapabilityProbe],
) -> tuple[DiagnosticCheck, GigaCodeCapabilities | None]:
    try:
        capabilities = await adapter_factory().detect_capabilities()
    except AgentRuntimeError as error:
        return (
            DiagnosticCheck(
                "error",
                "gigacode_unavailable",
                error.message,
                "Install GigaCode CLI or set gigacode.executable to its absolute path.",
                {"error_code": error.code.value},
            ),
            None,
        )
    except (OSError, RuntimeError) as error:
        return (
            DiagnosticCheck(
                "error",
                "gigacode_probe_failed",
                "GigaCode CLI capability probe failed",
                "Run the configured executable with --version and --help.",
                {"error_type": type(error).__name__},
            ),
            None,
        )

    required = {
        "model_selection",
        "system_prompt",
        "prompt",
        "agent_isolation",
        "approval_default",
        "approval_auto_edit",
        "json_output",
    }
    missing = sorted(name for name in required if not capabilities.available(name))
    if missing:
        return (
            DiagnosticCheck(
                "error",
                "gigacode_capabilities_missing",
                "GigaCode CLI is missing required runtime capabilities",
                "Upgrade or reconfigure the corporate GigaCode CLI.",
                {
                    "missing": missing,
                    "capabilities": capabilities.to_snapshot(),
                },
            ),
            capabilities,
        )
    return (
        DiagnosticCheck(
            "ok",
            "gigacode_capabilities_available",
            f"GigaCode CLI {capabilities.version} exposes required capabilities",
            details={"capabilities": capabilities.to_snapshot()},
        ),
        capabilities,
    )


async def _subprocess_smoke_check(
    config: EffectiveConfig,
    capabilities: GigaCodeCapabilities | None,
    *,
    enabled: bool,
) -> DiagnosticCheck:
    if not enabled:
        return DiagnosticCheck(
            "ok",
            "subprocess_smoke_not_requested",
            "Optional zero-data subprocess smoke was not requested",
            "Use diagnose --subprocess-smoke to test an additional CLI launch.",
        )
    if capabilities is None:
        return DiagnosticCheck(
            "error",
            "subprocess_smoke_blocked",
            "Subprocess smoke cannot run because GigaCode discovery failed",
            "Resolve the GigaCode executable diagnostic first.",
        )
    supervisor = ProcessSupervisor(
        max_stdout_bytes=64 * 1024,
        max_stderr_bytes=64 * 1024,
        graceful_cancel_seconds=1,
    )
    environment = {
        name: os.environ[name]
        for name in config.gigacode.environment_allowlist
        if name in os.environ
    }
    try:
        result = await supervisor.run(
            (capabilities.executable, "--version"),
            input_text="",
            cwd=capabilities.executable.parent,
            environment=environment,
            timeout_seconds=10,
        )
    except OSError as error:
        return DiagnosticCheck(
            "error",
            "subprocess_smoke_failed",
            "Zero-data GigaCode subprocess could not be started",
            "Check executable permissions and the configured environment allowlist.",
            {"error_type": type(error).__name__},
        )
    if result.returncode != 0 or result.timed_out:
        return DiagnosticCheck(
            "error",
            "subprocess_smoke_failed",
            "Zero-data GigaCode subprocess did not complete successfully",
            "Run the configured executable with --version.",
            {
                "returncode": result.returncode,
                "timed_out": result.timed_out,
            },
        )
    return DiagnosticCheck(
        "ok",
        "subprocess_smoke_passed",
        "Zero-data GigaCode subprocess completed successfully",
        details={"duration_seconds": round(result.duration_seconds, 3)},
    )


async def diagnose_runtime(
    config: EffectiveConfig,
    adapter_factory: Callable[[], CapabilityProbe],
    *,
    subprocess_smoke: bool = False,
) -> dict[str, object]:
    """Return a bounded machine-readable diagnostic report."""

    checks = [
        _os_check(),
        _python_check(),
        _version_check(),
        _mcp_sdk_check(),
        _directory_check(config),
        _web_bind_check(config),
        _model_allowlist_check(config),
        _permission_check(config),
    ]
    capability_check, capabilities = await _capabilities_check(adapter_factory)
    checks.append(capability_check)
    checks.append(
        await _subprocess_smoke_check(
            config,
            capabilities,
            enabled=subprocess_smoke,
        )
    )
    return {
        "status": _overall_status(checks),
        "checks": [check.to_document() for check in checks],
    }
