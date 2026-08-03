from __future__ import annotations

import re
from pathlib import Path

import pytest

from gigacode_agent_runtime.agent_catalog import AgentProfileCatalog
from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.plan_compiler import compile_plan
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.skill_catalog import SkillProfileCatalog

ROOT = Path(__file__).parents[2]
PUBLIC_DOCS = (
    ROOT / "README.md",
    *(path for path in (ROOT / "docs").glob("*.md")),
    ROOT / "optional-skill" / "SKILL.md",
)


def test_all_published_scenario_examples_validate_but_require_models(
    tmp_path: Path,
) -> None:
    config = load_config(home=tmp_path / "home")
    scenarios = sorted((ROOT / "examples" / "scenarios").glob("*.yaml"))

    assert len(scenarios) == 5
    for path in scenarios:
        scenario = load_scenario_file(
            path,
            agent_catalog=AgentProfileCatalog(ROOT / "examples" / "agents"),
        )
        with pytest.raises(AgentRuntimeError) as captured:
            compile_plan(
                scenario,
                config,
                inputs={"task": "documentation test"},
                workspace=tmp_path,
            )
        assert captured.value.code is ErrorCode.MODEL_NOT_ALLOWED
        assert captured.value.details["placeholder"] is True


def test_corporate_profile_is_ready_to_plan_without_edits(
    tmp_path: Path,
) -> None:
    profile = ROOT / "corporate-profile"
    config = load_config(profile / "config.yaml", home=tmp_path / "home")
    scenarios = sorted((profile / "scenarios").glob("*.yaml"))
    allowed_models = {
        "vllm/Qwen3.6-35B-262k",
        "vllm/DeepSeek-V4-Flash-0731-262k",
        "vllm/MiniMax-M3-161k",
        "GigaChat-3.1-Ultra-128k",
    }

    assert set(config.gigacode.model_allowlist) == allowed_models
    assert config.permissions.allow_full_access is True
    assert len(scenarios) == 6
    for path in scenarios:
        plan = compile_plan(
            load_scenario_file(
                path,
                agent_catalog=AgentProfileCatalog(profile / "agents"),
                skill_catalog=SkillProfileCatalog(profile / "skills"),
            ),
            config,
            inputs={"task": "corporate profile test"},
            workspace=tmp_path,
        )
        assert plan.metadata.name.startswith("corporate-")
        assert {agent.model for agent in plan.agents.values()} <= allowed_models


def test_optional_simple_skills_scenario_is_ready_for_installed_text_skills(
    tmp_path: Path,
) -> None:
    profile = ROOT / "corporate-profile"
    skills = tmp_path / "home" / ".gigacode" / "skills"
    for name in ("doc-review", "secure-coding"):
        directory = skills / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            f"description: Simple {name} proof.\n"
            "---\n\n"
            f"Apply {name} only to the supplied text.\n"
        )
    config = load_config(profile / "config.yaml", home=tmp_path / "home")
    scenario = load_scenario_file(
        profile
        / "optional-scenarios"
        / "corporate-simple-skills.yaml",
        skill_catalog=SkillProfileCatalog(skills),
    )

    plan = compile_plan(
        scenario,
        config,
        inputs={"task": "# API\nReview this short specification."},
        workspace=tmp_path,
    )

    assert plan.waves == (
        ("review_documentation", "review_security"),
        ("synthesize",),
    )
    assert [
        skill.reference
        for skill in plan.agents["documentation_reviewer"].skills
    ] == ["gigacode:doc-review"]
    assert [
        skill.reference for skill in plan.agents["security_reviewer"].skills
    ] == ["gigacode:secure-coding"]
    assert plan.agents["synthesizer"].skills == ()


def test_public_docs_have_no_personal_paths_or_assignment_secrets() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in PUBLIC_DOCS)

    assert "/Users/" not in combined
    assert re.search(r"(?i)(token|secret)\\s*=", combined) is None


def test_readme_scopes_v1_without_daemon_or_linux_promise() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", readme)

    assert "macOS `x86_64`" in readme
    assert "Linux не является поддерживаемой платформой v1" in normalized
    assert "Постоянно работающего фонового демона нет" in normalized
    assert "поддерживает Linux" not in readme
    assert "фоновый daemon" not in readme
