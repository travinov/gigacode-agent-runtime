from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.agent_catalog import AgentProfileCatalog
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.scenario_loader import ScenarioCatalog, load_scenario_file
from gigacode_agent_runtime.skill_catalog import SkillProfileCatalog

FIXTURES = Path(__file__).parents[1] / "fixtures" / "scenarios"


def _scenario_text(name: str, title: str) -> str:
    return f"""\
schema_version: gigacode-agent-runtime/scenario-v1
kind: Scenario
metadata:
  name: {name}
  title: {title}
agents:
  analyst:
    model: code-model-id
    permissions: read_only
    system_prompt: Analyze.
steps:
  analyze:
    kind: agent
    agent: analyst
    needs: []
    prompt:
      template: Analyze.
    output_schema:
      type: object
result:
  from: "${{steps.analyze.output}}"
"""


def test_valid_scenario_is_loaded_with_validated_templates() -> None:
    loaded = load_scenario_file(FIXTURES / "parallel-valid.yaml")

    assert loaded.name == "parallel-valid"
    assert loaded.source.level == "direct"
    assert loaded.resources == {}


def test_catalog_precedence_is_project_user_builtin(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    project = tmp_path / "project"
    for directory in (builtin, user, project):
        directory.mkdir()
    (builtin / "shared.yaml").write_text(_scenario_text("shared", "builtin"))
    (user / "shared.yaml").write_text(_scenario_text("shared", "user"))
    (project / "shared.yaml").write_text(_scenario_text("shared", "project"))

    catalog = ScenarioCatalog(builtin_dir=builtin, user_dir=user, project_dir=project)

    assert catalog.discover()["shared"].source.level == "project"


def test_duplicate_name_in_same_level_is_rejected(tmp_path: Path) -> None:
    user = tmp_path / "user"
    user.mkdir()
    (user / "one.yaml").write_text(_scenario_text("duplicate", "one"))
    (user / "two.yaml").write_text(_scenario_text("duplicate", "two"))
    catalog = ScenarioCatalog(user_dir=user)

    with pytest.raises(AgentRuntimeError) as captured:
        catalog.discover()

    assert captured.value.code is ErrorCode.SCENARIO_INVALID
    assert "duplicate" in captured.value.message


def test_file_reference_is_snapshotted(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yaml"
    prompt = tmp_path / "system.md"
    prompt.write_text("System instructions")
    scenario.write_text(
        _scenario_text("with-file", "with file").replace(
            "system_prompt: Analyze.",
            "system_prompt_file: system.md",
        )
    )

    loaded = load_scenario_file(scenario)

    assert loaded.resources["system.md"].content == "System instructions"


def test_scenario_path_escape_is_rejected(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    scenario_dir.mkdir()
    scenario = scenario_dir / "scenario.yaml"
    scenario.write_text((FIXTURES / "path-escape.yaml").read_text())
    (tmp_path / "outside-system-prompt.md").write_text("outside")

    with pytest.raises(AgentRuntimeError) as captured:
        load_scenario_file(scenario)

    assert captured.value.code is ErrorCode.PATH_NOT_ALLOWED


def test_agent_ref_is_snapshotted_from_native_catalog(tmp_path: Path) -> None:
    agents = tmp_path / "home" / ".gigacode" / "agents"
    agents.mkdir(parents=True)
    profile = agents / "analyst.md"
    profile.write_text(
        "---\n"
        "name: reusable-analyst\n"
        "description: Reusable analyst.\n"
        "tools: [read_file]\n"
        "---\n\n"
        "Analyze from the reusable profile.\n"
    )
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text(
        _scenario_text("with-agent-ref", "with agent ref").replace(
            "system_prompt: Analyze.",
            "agent_ref: gigacode:reusable-analyst",
        )
    )

    loaded = load_scenario_file(
        scenario,
        agent_catalog=AgentProfileCatalog(agents),
    )
    profile.write_text("changed after snapshot")

    assert loaded.agent_profiles["gigacode:reusable-analyst"].system_prompt == (
        "Analyze from the reusable profile."
    )
    assert loaded.resources["gigacode:reusable-analyst"].content.startswith("---")


def test_agent_ref_requires_configured_catalog(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text(
        _scenario_text("missing-agent-catalog", "missing agent catalog").replace(
            "system_prompt: Analyze.",
            "agent_ref: gigacode:reusable-analyst",
        )
    )

    with pytest.raises(AgentRuntimeError) as captured:
        load_scenario_file(scenario)

    assert captured.value.code is ErrorCode.AGENT_PROFILE_NOT_FOUND


def test_skill_refs_are_snapshotted_from_native_catalog(tmp_path: Path) -> None:
    skills = tmp_path / "home" / ".gigacode" / "skills"
    skill_dir = skills / "requirements-review"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\n"
        "name: requirements-review\n"
        "description: Review requirements.\n"
        "---\n\n"
        "Return a gap analysis.\n"
    )
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text(
        _scenario_text("with-skill-ref", "with skill ref").replace(
            "    system_prompt: Analyze.\n",
            "    system_prompt: Analyze.\n"
            "    skill_refs: [gigacode:requirements-review]\n",
        )
    )

    loaded = load_scenario_file(
        scenario,
        skill_catalog=SkillProfileCatalog(skills),
    )
    skill_file.write_text("changed after snapshot")

    assert loaded.skill_profiles["gigacode:requirements-review"].instructions == (
        "Return a gap analysis."
    )
    assert loaded.resources["skill:gigacode:requirements-review"].content.startswith(
        "---"
    )


def test_skill_refs_require_configured_catalog(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text(
        _scenario_text("missing-skill-catalog", "missing skill catalog").replace(
            "    system_prompt: Analyze.\n",
            "    system_prompt: Analyze.\n"
            "    skill_refs: [gigacode:requirements-review]\n",
        )
    )

    with pytest.raises(AgentRuntimeError) as captured:
        load_scenario_file(scenario)

    assert captured.value.code is ErrorCode.SKILL_PROFILE_NOT_FOUND
