from __future__ import annotations

import json
from pathlib import Path

from tests.cli.conftest import run_cli

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


def test_scenario_validate_and_plan_have_parseable_json(tmp_path: Path) -> None:
    validated = run_cli(
        tmp_path,
        "scenario",
        "validate",
        str(SCENARIOS / "minimal-valid.yaml"),
        "--json",
    )
    planned = run_cli(
        tmp_path,
        "scenario",
        "plan",
        str(SCENARIOS / "minimal-valid.yaml"),
        "--workspace",
        str(tmp_path),
        "--input",
        "task=inspect",
        "--json",
    )

    assert validated.returncode == 0
    assert json.loads(validated.stdout) == {"name": "minimal-valid", "valid": True}
    assert json.loads(planned.stdout)["waves"] == [["analyze"]]


def test_invalid_scenario_returns_exit_two_and_typed_json(tmp_path: Path) -> None:
    invalid = run_cli(
        tmp_path,
        "scenario",
        "validate",
        str(SCENARIOS / "cycle-invalid.yaml"),
        "--json",
    )

    assert invalid.returncode == 0
    # The cycle is a plan error rather than a document-shape error.
    planned = run_cli(
        tmp_path,
        "scenario",
        "plan",
        str(SCENARIOS / "cycle-invalid.yaml"),
        "--workspace",
        str(tmp_path),
        "--json",
    )
    error = json.loads(planned.stdout)["error"]
    assert planned.returncode == 2
    assert error["code"] == "SCENARIO_INVALID"


def test_agents_list_and_describe_use_native_user_catalog(tmp_path: Path) -> None:
    agents = tmp_path / "home" / ".gigacode" / "agents"
    agents.mkdir(parents=True)
    (agents / "analyst.md").write_text(
        "---\n"
        "name: reusable-analyst\n"
        "description: Reusable analyst.\n"
        "---\n\n"
        "Analyze requirements.\n"
    )

    listed = run_cli(tmp_path, "agents", "list", "--json")
    described = run_cli(
        tmp_path,
        "agents",
        "describe",
        "gigacode:reusable-analyst",
        "--json",
    )

    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)["agents"][0]["name"] == "reusable-analyst"
    assert described.returncode == 0, described.stderr
    assert json.loads(described.stdout)["system_prompt"] == "Analyze requirements."


def test_skills_list_and_describe_use_native_user_catalog(tmp_path: Path) -> None:
    skill_dir = (
        tmp_path
        / "home"
        / ".gigacode"
        / "skills"
        / "requirements-review"
    )
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: requirements-review\n"
        "description: Review requirements.\n"
        "---\n\n"
        "Return a gap analysis.\n"
    )

    listed = run_cli(tmp_path, "skills", "list", "--json")
    described = run_cli(
        tmp_path,
        "skills",
        "describe",
        "gigacode:requirements-review",
        "--json",
    )

    assert listed.returncode == 0, listed.stderr
    listed_document = json.loads(listed.stdout)
    assert listed_document["skills"][0]["skill_ref"] == (
        "gigacode:requirements-review"
    )
    assert listed_document["skills"][0]["source_level"] == "user"
    assert set(listed_document["catalog_roots"]) == {
        "user",
        "extension",
        "bundled",
    }
    assert described.returncode == 0, described.stderr
    assert json.loads(described.stdout)["instructions"] == "Return a gap analysis."
