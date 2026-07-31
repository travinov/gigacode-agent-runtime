from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.mcp_server import create_mcp_server
from gigacode_agent_runtime.mcp_tools import McpToolService
from tests.helpers.scheduler import scheduler_config
from tests.mcp.conftest import write_project_scenario

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_catalog_describe_validate_and_plan(tmp_path: Path) -> None:
    project = tmp_path / "project-scenarios"
    write_project_scenario(project, SCENARIOS / "minimal-valid.yaml")
    tools = McpToolService(
        scheduler_config(tmp_path),
        project_scenarios=project,
    )

    listed = await tools.list_scenarios()
    described = await tools.describe_scenario("minimal-valid")
    validated = await tools.validate_scenario(scenario_name="minimal-valid")
    planned = await tools.plan_scenario(
        scenario_name="minimal-valid",
        inputs={"task": "inspect"},
        workspace=str(tmp_path),
    )

    assert listed["data"]["scenarios"][0]["name"] == "minimal-valid"
    assert described["data"]["agents"]["analyst"]["model"] == "code-model-id"
    assert described["data"]["step_names"] == ["analyze"]
    assert described["data"]["steps"]["analyze"]["kind"] == "agent"
    assert described["data"]["steps"]["analyze"]["needs"] == []
    assert described["data"]["steps"]["analyze"]["output_schema"]["type"] == "object"
    assert described["data"]["result"] == {
        "from": "${steps.analyze.output}",
    }
    assert validated["data"]["valid"] is True
    assert planned["data"]["waves"] == [["analyze"]]


@pytest.mark.anyio
async def test_inline_scenario_validates_and_plans(tmp_path: Path) -> None:
    tools = McpToolService(scheduler_config(tmp_path))
    inline = (SCENARIOS / "sequential-valid.yaml").read_text()

    validated = await tools.validate_scenario(inline_scenario=inline)
    planned = await tools.plan_scenario(
        inline_scenario=inline,
        workspace=str(tmp_path),
    )

    assert validated["ok"] is True
    assert planned["data"]["scenario_name"] == "sequential-valid"


@pytest.mark.anyio
async def test_qwen_wire_contract_accepts_yaml_text_arguments(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project-scenarios"
    write_project_scenario(project, SCENARIOS / "minimal-valid.yaml")
    server = create_mcp_server(
        McpToolService(
            scheduler_config(tmp_path),
            project_scenarios=project,
        )
    )

    _content, planned = await server.call_tool(
        "plan_scenario",
        {
            "scenario_name": "minimal-valid",
            "workspace": str(tmp_path),
            "inputs_yaml": "task: inspect the corporate runtime\n",
        },
    )
    _content, validated = await server.call_tool(
        "validate_scenario",
        {
            "inline_scenario_yaml": (
                SCENARIOS / "sequential-valid.yaml"
            ).read_text(),
        },
    )

    assert planned["ok"] is True
    assert planned["data"]["inputs"] == {
        "task": "inspect the corporate runtime",
    }
    assert validated["data"]["valid"] is True


@pytest.mark.anyio
async def test_qwen_wire_contract_rejects_non_mapping_inputs_yaml(
    tmp_path: Path,
) -> None:
    server = create_mcp_server(McpToolService(scheduler_config(tmp_path)))

    _content, response = await server.call_tool(
        "plan_scenario",
        {
            "scenario_name": "sequential",
            "workspace": str(tmp_path),
            "inputs_yaml": "- not\n- a\n- mapping\n",
        },
    )

    assert response == {
        "ok": False,
        "error": {
            "code": "SCENARIO_INVALID",
            "message": "inputs_yaml must decode to a mapping with string keys",
            "details": {"parameter": "inputs_yaml"},
            "retryable": False,
        },
    }


@pytest.mark.anyio
async def test_qwen_wire_contract_rejects_non_json_yaml_values(
    tmp_path: Path,
) -> None:
    server = create_mcp_server(McpToolService(scheduler_config(tmp_path)))

    _content, response = await server.call_tool(
        "plan_scenario",
        {
            "scenario_name": "sequential",
            "workspace": str(tmp_path),
            "inputs_yaml": "task: 2026-07-30\n",
        },
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "SCENARIO_INVALID"
    assert response["error"]["message"] == (
        "inputs_yaml must contain only JSON-compatible values"
    )


@pytest.mark.anyio
async def test_builtin_placeholder_cannot_be_planned(tmp_path: Path) -> None:
    tools = McpToolService(scheduler_config(tmp_path))

    planned = await tools.plan_scenario(
        scenario_name="sequential",
        inputs={"task": "must configure models first"},
        workspace=str(tmp_path),
    )

    assert planned["ok"] is False
    assert planned["error"]["code"] == "MODEL_NOT_ALLOWED"
    assert planned["error"]["details"]["placeholder"] is True


@pytest.mark.anyio
async def test_agent_profiles_are_discovered_described_and_planned(
    tmp_path: Path,
) -> None:
    agents = tmp_path / "home" / ".gigacode" / "agents"
    agents.mkdir(parents=True)
    (agents / "analyst.md").write_text(
        "---\n"
        "name: reusable-analyst\n"
        "description: Reusable requirements analyst.\n"
        "color: Purple\n"
        "---\n\n"
        "Turn vague requests into testable requirements.\n"
    )
    project = tmp_path / "project-scenarios"
    source = (SCENARIOS / "minimal-valid.yaml").read_text().replace(
        "system_prompt: Analyze the task and return structured JSON.",
        "agent_ref: gigacode:reusable-analyst",
    )
    project.mkdir()
    (project / "agent-ref.yaml").write_text(source)
    tools = McpToolService(
        scheduler_config(tmp_path),
        project_scenarios=project,
    )

    listed = await tools.list_agent_profiles()
    described = await tools.describe_agent_profile("reusable-analyst")
    scenario = await tools.describe_scenario("minimal-valid")
    validated = await tools.validate_scenario(scenario_name="minimal-valid")
    planned = await tools.plan_scenario(
        scenario_name="minimal-valid",
        inputs={"task": "formalize"},
        workspace=str(tmp_path),
    )

    assert listed["data"]["agents"][0]["agent_ref"] == (
        "gigacode:reusable-analyst"
    )
    assert described["data"]["system_prompt"] == (
        "Turn vague requests into testable requirements."
    )
    assert scenario["data"]["resolved_agent_refs"][0]["name"] == (
        "reusable-analyst"
    )
    assert validated["data"]["agent_refs"] == ["gigacode:reusable-analyst"]
    assert planned["data"]["agents"]["analyst"]["source_ref"] == (
        "gigacode:reusable-analyst"
    )
    assert planned["data"]["resource_hashes"]["gigacode:reusable-analyst"].startswith(
        "sha256:"
    )


@pytest.mark.anyio
async def test_skill_profiles_are_discovered_described_and_allowlisted(
    tmp_path: Path,
) -> None:
    skills = tmp_path / "home" / ".gigacode" / "skills"
    skill_dir = skills / "requirements-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: requirements-review\n"
        "description: Review requirements for omissions.\n"
        "priority: 10\n"
        "---\n\n"
        "Return a gap analysis.\n"
    )
    project = tmp_path / "project-scenarios"
    source = (SCENARIOS / "minimal-valid.yaml").read_text().replace(
        "    permissions: read_only\n",
        "    permissions: read_only\n"
        "    skill_refs: [gigacode:requirements-review]\n",
    )
    project.mkdir()
    (project / "skill-ref.yaml").write_text(source)
    tools = McpToolService(
        scheduler_config(tmp_path),
        project_scenarios=project,
    )

    listed = await tools.list_skill_profiles()
    described = await tools.describe_skill_profile("requirements-review")
    scenario = await tools.describe_scenario("minimal-valid")
    validated = await tools.validate_scenario(scenario_name="minimal-valid")
    planned = await tools.plan_scenario(
        scenario_name="minimal-valid",
        inputs={"task": "formalize"},
        workspace=str(tmp_path),
    )

    assert listed["data"]["skills"][0]["skill_ref"] == (
        "gigacode:requirements-review"
    )
    assert described["data"]["instructions"] == "Return a gap analysis."
    assert scenario["data"]["resolved_skill_refs"][0]["name"] == (
        "requirements-review"
    )
    assert validated["data"]["skill_refs"] == ["gigacode:requirements-review"]
    assert planned["data"]["agents"]["analyst"]["skills"][0]["reference"] == (
        "gigacode:requirements-review"
    )
    assert planned["data"]["agents"]["analyst"]["skills"][0][
        "source_level"
    ] == "user"
    assert planned["data"]["resource_hashes"][
        "skill:gigacode:requirements-review"
    ].startswith("sha256:")


@pytest.mark.anyio
async def test_skill_profiles_include_extensions_bundled_and_shadowed_sources(
    tmp_path: Path,
) -> None:
    gigacode = tmp_path / "home" / ".gigacode"
    canonical = gigacode / "skills" / "bpmn-architect"
    alias = gigacode / "skills" / "publish-bpmn-skill"
    drawio = gigacode / "extensions" / "publish-drawio-skill"
    service = (
        gigacode
        / "extensions"
        / "service-extension"
        / "skills"
        / "service-analyst"
    )
    review = gigacode / "bin" / "bundled" / "review"
    for directory, name in (
        (canonical, "bpmn-architect"),
        (alias, "bpmn-architect"),
        (drawio, "drawio-skill"),
        (service, "service-analyst"),
        (review, "review"),
    ):
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            f"description: {name} description.\n"
            "---\n\n"
            f"Apply {name}.\n"
        )

    tools = McpToolService(scheduler_config(tmp_path))
    listed = await tools.list_skill_profiles()
    described = await tools.describe_skill_profile("drawio-skill")

    assert listed["ok"] is True
    assert listed["data"]["catalog_roots"] == {
        "user": str(gigacode / "skills"),
        "extension": str(gigacode / "extensions"),
        "bundled": str(gigacode / "bin" / "bundled"),
    }
    by_name = {
        item["name"]: item for item in listed["data"]["skills"]
    }
    assert by_name["bpmn-architect"]["source_path"] == str(
        (canonical / "SKILL.md").resolve()
    )
    assert by_name["bpmn-architect"]["shadowed_sources"] == [
        {
            "source_level": "user",
            "source_path": str((alias / "SKILL.md").resolve()),
            "canonical_directory": False,
        }
    ]
    assert by_name["drawio-skill"]["source_level"] == "extension"
    assert by_name["service-analyst"]["source_level"] == "extension"
    assert by_name["review"]["source_level"] == "bundled"
    assert described["data"]["instructions"] == "Apply drawio-skill."
