from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.adapters.capabilities import (
    GigaCodeCapabilities,
    find_gigacode_executable,
    parse_capabilities,
)
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode


def test_qwen_help_is_parsed_by_feature_not_only_version() -> None:
    capabilities = parse_capabilities(
        Path("/opt/gigacode"),
        "26.5.17",
        """
        --model
        --system-prompt
        --approval-mode <plan|default|auto-edit>
        --allowed-tools
        --sandbox
        --input-format <text|stream-json>
        --output-format <text|json|stream-json>
        """,
        "Usage: qwen mcp <add|remove|list>",
    )

    assert capabilities.model_selection is True
    assert capabilities.sandbox is True
    assert capabilities.stream_input is True
    assert capabilities.stream_output is True
    assert capabilities.approval_modes == frozenset({"plan", "default", "auto-edit"})
    assert capabilities.mcp is True


def test_unknown_help_does_not_claim_dangerous_capabilities() -> None:
    capabilities = parse_capabilities(Path("/opt/gigacode"), "unknown", "Usage", "")

    assert capabilities.sandbox is False
    assert capabilities.allowed_tools is False
    assert capabilities.approval_modes == frozenset()


def test_missing_required_capability_is_typed_error() -> None:
    capabilities = GigaCodeCapabilities.empty(Path("/opt/gigacode"))

    with pytest.raises(AgentRuntimeError) as captured:
        capabilities.require({"sandbox"})

    assert captured.value.code is ErrorCode.CAPABILITY_UNAVAILABLE


def test_explicit_missing_executable_is_not_guessed(tmp_path: Path) -> None:
    missing = tmp_path / "missing-gigacode"

    with pytest.raises(AgentRuntimeError) as captured:
        find_gigacode_executable(str(missing), home=tmp_path, path="")

    assert captured.value.code is ErrorCode.CAPABILITY_UNAVAILABLE
