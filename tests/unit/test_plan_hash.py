from __future__ import annotations

from pathlib import Path

from gigacode_agent_runtime.agent_catalog import AgentProfileCatalog
from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.plan_compiler import compile_plan
from gigacode_agent_runtime.scenario_loader import load_scenario_file

FIXTURES = Path(__file__).parents[1] / "fixtures" / "scenarios"


def _compile(path: Path, tmp_path: Path):
    return compile_plan(
        load_scenario_file(path),
        load_config(tmp_path / "missing.yaml", home=tmp_path / "home"),
        inputs={},
        workspace=tmp_path / "workspace",
    )


def test_mapping_order_does_not_change_plan_hash(tmp_path: Path) -> None:
    original = (FIXTURES / "sequential-valid.yaml").read_text()
    reordered = original.replace(
        "  create:\n",
        "  z_create:\n",
    ).replace(
        "needs: [create]",
        "needs: [z_create]",
    ).replace(
        "steps.create.output",
        "steps.z_create.output",
    )
    first_path = tmp_path / "first.yaml"
    second_path = tmp_path / "second.yaml"
    first_path.write_text(reordered)
    second_path.write_text(
        reordered.replace(
            "  z_create:\n"
            "    kind: agent\n"
            "    agent: creator\n"
            "    needs: []\n"
            "    prompt:\n"
            "      template: Create a draft.\n"
            "    output_schema:\n"
            "      type: object\n\n"
            "  review:",
            "  review:",
        )
        .replace(
            "  review:\n"
            "    kind: agent\n"
            "    agent: reviewer\n"
            "    needs: [z_create]\n"
            "    prompt:\n"
            "      template: \"Review: ${steps.z_create.output}\"\n"
            "    output_schema:\n"
            "      type: object\n",
            "  review:\n"
            "    kind: agent\n"
            "    agent: reviewer\n"
            "    needs: [z_create]\n"
            "    prompt:\n"
            "      template: \"Review: ${steps.z_create.output}\"\n"
            "    output_schema:\n"
            "      type: object\n\n"
            "  z_create:\n"
            "    kind: agent\n"
            "    agent: creator\n"
            "    needs: []\n"
            "    prompt:\n"
            "      template: Create a draft.\n"
            "    output_schema:\n"
            "      type: object\n",
        )
    )

    assert _compile(first_path, tmp_path).plan_hash == _compile(second_path, tmp_path).plan_hash


def test_prompt_change_changes_plan_hash(tmp_path: Path) -> None:
    original = (FIXTURES / "sequential-valid.yaml").read_text()
    first_path = tmp_path / "first.yaml"
    second_path = tmp_path / "second.yaml"
    first_path.write_text(original)
    second_path.write_text(original.replace("Create a draft.", "Create a different draft."))

    assert _compile(first_path, tmp_path).plan_hash != _compile(second_path, tmp_path).plan_hash


def test_reusable_agent_change_changes_plan_hash(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    agents.mkdir()
    agent = agents / "analyst.md"
    scenario_path = tmp_path / "agent-ref.yaml"
    scenario_path.write_text(
        (FIXTURES / "minimal-valid.yaml").read_text().replace(
            "system_prompt: Analyze the task and return structured JSON.",
            "agent_ref: gigacode:reusable-analyst",
        )
    )

    def compile_with_prompt(prompt: str):
        agent.write_text(
            "---\n"
            "name: reusable-analyst\n"
            "description: Reusable analyst.\n"
            "---\n\n"
            f"{prompt}\n"
        )
        return compile_plan(
            load_scenario_file(
                scenario_path,
                agent_catalog=AgentProfileCatalog(agents),
            ),
            load_config(tmp_path / "missing.yaml", home=tmp_path / "home"),
            inputs={"task": "inspect"},
            workspace=tmp_path,
        )

    first = compile_with_prompt("First instructions.")
    second = compile_with_prompt("Second instructions.")

    assert first.plan_hash != second.plan_hash
    assert first.agents["analyst"].source_hash != second.agents["analyst"].source_hash
