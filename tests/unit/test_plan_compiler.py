from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.agent_catalog import AgentProfileCatalog
from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.domain import LoopStepDefinition
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.plan_compiler import compile_plan, execution_plan_to_document
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.schema_registry import validate_document
from gigacode_agent_runtime.skill_catalog import SkillProfileCatalog

FIXTURES = Path(__file__).parents[1] / "fixtures" / "scenarios"


def _config(tmp_path: Path):
    return load_config(tmp_path / "missing-config.yaml", home=tmp_path / "home")


def test_sequential_and_parallel_scenarios_compile_to_expected_waves(tmp_path: Path) -> None:
    sequential = compile_plan(
        load_scenario_file(FIXTURES / "sequential-valid.yaml"),
        _config(tmp_path),
        inputs={},
        workspace=tmp_path,
    )
    parallel = compile_plan(
        load_scenario_file(FIXTURES / "parallel-valid.yaml"),
        _config(tmp_path),
        inputs={"task": "compare"},
        workspace=tmp_path,
    )

    assert sequential.waves == (("create",), ("review",))
    assert parallel.waves == (("analyze_first", "analyze_second"), ("review",))
    assert "approval_default" in sequential.capability_requirements
    assert "approval_plan" not in sequential.capability_requirements
    assert "agent_isolation" in sequential.capability_requirements
    assert "prompt" in sequential.capability_requirements
    assert "stream_json" not in sequential.capability_requirements
    validate_document("execution-plan-v1", execution_plan_to_document(parallel))


def test_cycle_is_rejected_before_execution(tmp_path: Path) -> None:
    loaded = load_scenario_file(FIXTURES / "cycle-invalid.yaml")

    with pytest.raises(AgentRuntimeError) as captured:
        compile_plan(loaded, _config(tmp_path), inputs={}, workspace=tmp_path)

    assert captured.value.code is ErrorCode.SCENARIO_INVALID


def test_missing_required_input_is_rejected(tmp_path: Path) -> None:
    loaded = load_scenario_file(FIXTURES / "parallel-valid.yaml")

    with pytest.raises(AgentRuntimeError) as captured:
        compile_plan(loaded, _config(tmp_path), inputs={}, workspace=tmp_path)

    assert captured.value.code is ErrorCode.SCENARIO_INVALID
    assert captured.value.details["input"] == "task"


def test_model_allowlist_is_enforced(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "schema_version: gigacode-agent-runtime/config-v1\n"
        "gigacode:\n  model_allowlist: [another-model]\n"
    )
    loaded = load_scenario_file(FIXTURES / "sequential-valid.yaml")

    with pytest.raises(AgentRuntimeError) as captured:
        compile_plan(
            loaded,
            load_config(config_path, home=tmp_path),
            inputs={},
            workspace=tmp_path,
        )

    assert captured.value.code is ErrorCode.MODEL_NOT_ALLOWED


def test_placeholder_model_is_rejected_before_execution(tmp_path: Path) -> None:
    source = (FIXTURES / "sequential-valid.yaml").read_text()
    path = tmp_path / "placeholder.yaml"
    path.write_text(
        source.replace("code-model-id", "REPLACE_WITH_GIGACODE_MODEL_ID")
    )

    with pytest.raises(AgentRuntimeError) as captured:
        compile_plan(
            load_scenario_file(path),
            _config(tmp_path),
            inputs={},
            workspace=tmp_path,
        )

    assert captured.value.code is ErrorCode.MODEL_NOT_ALLOWED
    assert captured.value.details == {
        "agent": "creator",
        "model": "REPLACE_WITH_GIGACODE_MODEL_ID",
        "placeholder": True,
    }
    assert "placeholder" in captured.value.message


def test_full_access_loop_is_capped_by_global_policy(tmp_path: Path) -> None:
    plan = compile_plan(
        load_scenario_file(FIXTURES / "full-access-loop.yaml"),
        _config(tmp_path),
        inputs={},
        workspace=tmp_path,
    )

    loop = plan.steps[0]
    assert isinstance(loop, LoopStepDefinition)
    assert loop.max_iterations == 3
    assert "approval_auto_edit" in plan.capability_requirements


def test_scenario_cannot_raise_global_parallel_limit(tmp_path: Path) -> None:
    document = (FIXTURES / "parallel-valid.yaml").read_text().replace(
        "steps:\n",
        "max_parallel_agents: 20\n\nsteps:\n",
    )
    path = tmp_path / "too-parallel.yaml"
    path.write_text(document)

    with pytest.raises(AgentRuntimeError) as captured:
        compile_plan(
            load_scenario_file(path),
            _config(tmp_path),
            inputs={"task": "compare"},
            workspace=tmp_path,
        )

    assert captured.value.code is ErrorCode.SCENARIO_INVALID


def test_agent_ref_resolves_prompt_tools_and_provenance(tmp_path: Path) -> None:
    agents = tmp_path / "home" / ".gigacode" / "agents"
    agents.mkdir(parents=True)
    (agents / "analyst.md").write_text(
        "---\n"
        "name: reusable-analyst\n"
        "description: Reusable analyst.\n"
        "tools: [read_file, grep_search]\n"
        "disallowedTools: [grep_search]\n"
        "---\n\n"
        "Analyze using the reusable role.\n"
    )
    scenario_path = tmp_path / "agent-ref.yaml"
    scenario_path.write_text(
        (FIXTURES / "minimal-valid.yaml").read_text().replace(
            "system_prompt: Analyze the task and return structured JSON.",
            "agent_ref: gigacode:reusable-analyst",
        )
    )
    loaded = load_scenario_file(
        scenario_path,
        agent_catalog=AgentProfileCatalog(agents),
    )

    plan = compile_plan(
        loaded,
        _config(tmp_path),
        inputs={"task": "inspect"},
        workspace=tmp_path,
    )
    agent = plan.agents["analyst"]

    assert agent.system_prompt == "Analyze using the reusable role."
    assert agent.allowed_tools == ("read_file",)
    assert agent.source_ref == "gigacode:reusable-analyst"
    assert agent.source_hash == plan.resource_hashes["gigacode:reusable-analyst"]


def test_skill_refs_inject_only_selected_skill_and_record_provenance(
    tmp_path: Path,
) -> None:
    skills = tmp_path / "home" / ".gigacode" / "skills"
    selected = skills / "requirements-review"
    unselected = skills / "unselected"
    selected.mkdir(parents=True)
    unselected.mkdir()
    (selected / "SKILL.md").write_text(
        "---\n"
        "name: requirements-review\n"
        "description: Review requirements.\n"
        "---\n\n"
        "SELECTED_SKILL_INSTRUCTION\n"
    )
    (unselected / "SKILL.md").write_text(
        "---\n"
        "name: unselected\n"
        "description: Must remain unavailable.\n"
        "---\n\n"
        "UNSELECTED_SKILL_INSTRUCTION\n"
    )
    scenario_path = tmp_path / "skill-ref.yaml"
    scenario_path.write_text(
        (FIXTURES / "minimal-valid.yaml").read_text().replace(
            "    permissions: read_only\n",
            "    permissions: read_only\n"
            "    skill_refs: [gigacode:requirements-review]\n",
        )
    )
    loaded = load_scenario_file(
        scenario_path,
        skill_catalog=SkillProfileCatalog(skills),
    )

    plan = compile_plan(
        loaded,
        _config(tmp_path),
        inputs={"task": "inspect"},
        workspace=tmp_path,
    )
    agent = plan.agents["analyst"]

    assert "SELECTED_SKILL_INSTRUCTION" in agent.system_prompt
    assert "UNSELECTED_SKILL_INSTRUCTION" not in agent.system_prompt
    assert [skill.reference for skill in agent.skills] == [
        "gigacode:requirements-review"
    ]
    assert agent.skills[0].source_level == "user"
    assert agent.skills[0].source_path == (selected / "SKILL.md").resolve()
    assert agent.skills[0].source_hash == plan.resource_hashes[
        "skill:gigacode:requirements-review"
    ]
    assert "tool_exclusion" in plan.capability_requirements
    validate_document("execution-plan-v1", execution_plan_to_document(plan))
