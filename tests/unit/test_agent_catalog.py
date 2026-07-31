from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.agent_catalog import (
    AgentProfileCatalog,
    agent_name_from_reference,
    load_agent_profile,
)
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode


def _agent(
    name: str = "business-analyst-proactive",
    *,
    extra: str = "",
    prompt: str = "Analyze requirements.",
) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        "description: Turns vague ideas into requirements.\n"
        f"{extra}"
        "---\n\n"
        f"{prompt}\n"
    )


def test_native_markdown_agent_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "business.md"
    path.write_text(
        _agent(
            extra=(
                "model: vllm/Qwen3.6-35B-262k\n"
                "approvalMode: plan\n"
                "color: Purple\n"
                "tools: [read_file, grep_search]\n"
                "disallowedTools: [grep_search]\n"
            )
        )
    )

    profile = load_agent_profile(path)

    assert profile.reference == "gigacode:business-analyst-proactive"
    assert profile.model == "vllm/Qwen3.6-35B-262k"
    assert profile.approval_mode == "plan"
    assert profile.tools == ("read_file", "grep_search")
    assert profile.disallowed_tools == ("grep_search",)
    assert profile.system_prompt == "Analyze requirements."


def test_catalog_discovers_agents_by_front_matter_name(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    root.mkdir()
    (root / "arbitrary-file-name.md").write_text(_agent())

    catalog = AgentProfileCatalog(root)

    assert list(catalog.discover()) == ["business-analyst-proactive"]
    assert catalog.load("gigacode:business-analyst-proactive").name == (
        "business-analyst-proactive"
    )
    assert agent_name_from_reference("gigacode:business-analyst-proactive") == (
        "business-analyst-proactive"
    )


def test_catalog_missing_agent_has_stable_error(tmp_path: Path) -> None:
    with pytest.raises(AgentRuntimeError) as captured:
        AgentProfileCatalog(tmp_path / "missing").load("missing-agent")

    assert captured.value.code is ErrorCode.AGENT_PROFILE_NOT_FOUND
    assert captured.value.details["name"] == "missing-agent"


@pytest.mark.parametrize(
    "content",
    (
        "No front matter\n",
        "---\nname: agent\ndescription: present\n---\n",
        "---\nname: bad/name\ndescription: present\n---\nPrompt\n",
        "---\nname: agent\ndescription: present\ntools: read_file\n---\nPrompt\n",
    ),
)
def test_invalid_agent_file_is_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "invalid.md"
    path.write_text(content)

    with pytest.raises(AgentRuntimeError) as captured:
        load_agent_profile(path)

    assert captured.value.code is ErrorCode.AGENT_PROFILE_INVALID


def test_duplicate_agent_name_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    root.mkdir()
    (root / "one.md").write_text(_agent("duplicate"))
    (root / "two.md").write_text(_agent("duplicate"))

    with pytest.raises(AgentRuntimeError) as captured:
        AgentProfileCatalog(root).discover()

    assert captured.value.code is ErrorCode.AGENT_PROFILE_INVALID
    assert "Duplicate" in captured.value.message


def test_symlinked_agent_file_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    root.mkdir()
    target = tmp_path / "outside.md"
    target.write_text(_agent("linked"))
    (root / "linked.md").symlink_to(target)

    with pytest.raises(AgentRuntimeError) as captured:
        AgentProfileCatalog(root).discover()

    assert captured.value.code is ErrorCode.PATH_NOT_ALLOWED
