from __future__ import annotations

import re
from pathlib import Path

from gigacode_agent_runtime.mcp_server import TOOL_NAMES

ROOT = Path(__file__).parents[2]
SKILL = ROOT / "optional-skill" / "SKILL.md"


def test_optional_skill_uses_only_discovered_mcp_tools() -> None:
    text = SKILL.read_text(encoding="utf-8")
    mentioned = set(re.findall(r"`([a-z][a-z0-9_]+)`", text))
    tool_like = {
        name
        for name in mentioned
        if name != "plan_hash"
        if name.startswith(
            (
                "list_",
                "describe_",
                "validate_",
                "plan_",
                "diagnose_",
                "start_",
                "get_",
                "provide_",
                "approve_",
                "pause_",
                "resume_",
                "cancel_",
                "open_",
            )
        )
    }

    assert tool_like
    assert tool_like <= set(TOOL_NAMES)


def test_optional_skill_enforces_runtime_workflow() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert text.index("`validate_scenario`") < text.index("`plan_scenario`")
    assert text.index("`plan_scenario`") < text.index("`start_run`")
    assert "Do not recreate its scheduler" in text
    assert "`inputs_yaml`" in text
    assert "never JSON-encode the mapping" in text
    assert "never fall back to Shell" in text
    assert "Draw.io" not in text
