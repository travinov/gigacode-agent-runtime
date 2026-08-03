from __future__ import annotations

import re
from pathlib import Path

import pytest

from gigacode_agent_runtime.agent_catalog import AgentProfileCatalog, load_agent_profile
from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.plan_compiler import compile_plan
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.skill_catalog import SkillProfileCatalog, load_skill_profile
from gigacode_agent_runtime.yaml_loader import safe_load

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
    assert len(scenarios) == 7
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


def test_all_fields_examples_cover_every_supported_object_field(
    tmp_path: Path,
) -> None:
    profile = ROOT / "corporate-profile"
    agent = load_agent_profile(
        profile / "agents" / "runtime-all-fields-example.md",
        expected_root=profile / "agents",
    )
    assert agent.model == "vllm/Qwen3.6-35B-262k"
    assert agent.approval_mode == "plan"
    assert agent.color == "Purple"
    assert agent.tools == ("read_file", "grep_search", "glob", "list_directory")
    assert agent.disallowed_tools == ("write_file", "edit", "run_shell_command")

    skill = load_skill_profile(
        profile / "skills" / "runtime-all-fields-example" / "SKILL.md",
        expected_root=profile / "skills",
    )
    assert skill.priority == 50
    assert skill.paths == ("**/*.md", "**/*.yaml", "**/*.json")
    assert skill.user_invocable is True
    assert skill.disable_model_invocation is True

    raw_config = safe_load((ROOT / "examples" / "config-all-fields.yaml").read_text())
    assert isinstance(raw_config, dict)
    assert set(raw_config) == {
        "schema_version",
        "runtime",
        "gigacode",
        "permissions",
        "web",
    }
    assert set(raw_config["runtime"]) == {
        "data_dir",
        "max_parallel_agents",
        "default_step_timeout_seconds",
        "graceful_cancel_seconds",
        "max_stdout_bytes_per_step",
        "max_stderr_bytes_per_step",
    }
    assert set(raw_config["gigacode"]) == {
        "executable",
        "model_allowlist",
        "environment_allowlist",
    }
    assert set(raw_config["permissions"]) == {
        "default",
        "allow_full_access",
        "require_full_access_confirmation",
        "max_parallel_full_access_agents",
        "max_full_access_loop_iterations",
        "trusted_scenario_hashes",
    }
    assert set(raw_config["web"]) == {
        "enabled",
        "host",
        "port",
        "open_automatically",
    }
    load_config(ROOT / "examples" / "config-all-fields.yaml", home=tmp_path / "home")

    scenario = load_scenario_file(
        profile / "scenarios" / "corporate-all-fields-example.yaml",
        agent_catalog=AgentProfileCatalog(profile / "agents"),
        skill_catalog=SkillProfileCatalog(profile / "skills"),
    )
    document = scenario.document
    assert {definition["type"] for definition in document["inputs"].values()} == {
        "string",
        "integer",
        "number",
        "boolean",
        "object",
        "array",
    }
    assert {definition["permissions"] for definition in document["agents"].values()} == {
        "read_only",
        "propose_only",
        "workspace_write",
        "full_access",
    }
    assert any("agent_ref" in definition for definition in document["agents"].values())
    assert any("system_prompt" in definition for definition in document["agents"].values())
    assert any("system_prompt_file" in definition for definition in document["agents"].values())
    inspect = document["steps"]["inspect"]
    assert set(inspect["retry"]) == {"max_attempts", "backoff_seconds", "on"}
    assert "context" in inspect["prompt"] and "when" in inspect
    file_step = document["steps"]["file_backed_validation"]
    assert "template_file" in file_step["prompt"]
    assert isinstance(file_step["output_schema"], str)
    loop = document["steps"]["bounded_review_loop"]
    assert set(loop) == {
        "kind",
        "needs",
        "max_iterations",
        "timeout_seconds",
        "on_limit",
        "no_progress",
        "body",
        "until",
    }
    conditions_text = str((inspect["when"], loop["until"]))
    assert all(f"'{operator}'" in conditions_text for operator in ("all", "any", "not"))

    plan = compile_plan(
        scenario,
        load_config(profile / "config.yaml", home=tmp_path / "home"),
        inputs={"task": "validate all fields"},
        workspace=tmp_path,
    )
    assert plan.metadata.name == "corporate-all-fields-example"
    assert plan.waves == (
        ("inspect",),
        ("file_backed_validation", "parallel_review"),
        ("bounded_review_loop",),
    )
    assert plan.agents["gated_full_access"].allowed_tools == ("read_file",)


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
