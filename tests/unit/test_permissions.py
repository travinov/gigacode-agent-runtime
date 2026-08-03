from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.adapters.capabilities import GigaCodeCapabilities
from gigacode_agent_runtime.approval_store import ApprovalStore
from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.permissions import PermissionController
from gigacode_agent_runtime.plan_compiler import compile_plan
from gigacode_agent_runtime.scenario_loader import load_scenario_file

FIXTURES = Path(__file__).parents[1] / "fixtures" / "scenarios"


def _config(tmp_path: Path, *, allow_full_access: bool, trusted_hash: str | None = None):
    config_path = tmp_path / "config.yaml"
    trusted = (
        "\n  trusted_scenario_hashes:\n"
        f"    full-access-loop: {trusted_hash}\n"
        if trusted_hash
        else ""
    )
    config_path.write_text(
        "schema_version: gigacode-agent-runtime/config-v1\n"
        "permissions:\n"
        f"  allow_full_access: {'true' if allow_full_access else 'false'}\n"
        "  require_full_access_confirmation: true\n"
        f"{trusted}"
    )
    return load_config(config_path, home=tmp_path / "home")


def _plan(tmp_path: Path, config):
    return compile_plan(
        load_scenario_file(FIXTURES / "full-access-loop.yaml"),
        config,
        inputs={},
        workspace=tmp_path,
    )


def _capabilities(*, allowed_tools: bool = True) -> GigaCodeCapabilities:
    return GigaCodeCapabilities(
        executable=Path("/opt/gigacode"),
        version="26.5.17",
        model_selection=True,
        system_prompt=True,
        prompt=True,
        approval_modes=frozenset({"plan", "default", "auto-edit"}),
        allowed_tools=allowed_tools,
        sandbox=True,
        stream_input=True,
        json_output=True,
        stream_output=True,
        agent_isolation=True,
        mcp=True,
    )


def test_full_access_is_denied_when_global_switch_is_off(tmp_path: Path) -> None:
    config = _config(tmp_path, allow_full_access=False)
    plan = _plan(tmp_path, config)
    controller = PermissionController(config, ApprovalStore(tmp_path / "run"))

    with pytest.raises(AgentRuntimeError) as captured:
        controller.authorize(plan, "run_example", _capabilities())

    assert captured.value.code is ErrorCode.PERMISSION_DENIED


def test_full_access_requires_confirmation_for_exact_plan_hash(tmp_path: Path) -> None:
    config = _config(tmp_path, allow_full_access=True)
    plan = _plan(tmp_path, config)
    approvals = ApprovalStore(tmp_path / "run")
    controller = PermissionController(config, approvals)

    with pytest.raises(AgentRuntimeError) as captured:
        controller.authorize(plan, "run_example", _capabilities())

    assert captured.value.code is ErrorCode.APPROVAL_REQUIRED
    approvals.approve("run_example", plan.plan_hash, "full_access")
    decision = controller.authorize(plan, "run_example", _capabilities())
    assert decision.full_access is True


def test_trusted_scenario_hash_skips_interactive_confirmation(tmp_path: Path) -> None:
    first_config = _config(tmp_path, allow_full_access=True)
    first_plan = _plan(tmp_path, first_config)
    trusted_config = _config(
        tmp_path,
        allow_full_access=True,
        trusted_hash=first_plan.plan_hash,
    )
    trusted_plan = _plan(tmp_path, trusted_config)
    controller = PermissionController(trusted_config, ApprovalStore(tmp_path / "run"))

    assert trusted_plan.plan_hash == first_plan.plan_hash
    assert controller.authorize(
        trusted_plan, "run_example", _capabilities()
    ).trusted_hash is True


def test_missing_cli_full_access_capability_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path, allow_full_access=True)
    plan = _plan(tmp_path, config)
    approvals = ApprovalStore(tmp_path / "run")
    approvals.approve("run_example", plan.plan_hash, "full_access")
    controller = PermissionController(config, approvals)

    with pytest.raises(AgentRuntimeError) as captured:
        controller.authorize(
            plan,
            "run_example",
            _capabilities(allowed_tools=False),
        )

    assert captured.value.code is ErrorCode.CAPABILITY_UNAVAILABLE
