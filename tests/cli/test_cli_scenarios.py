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
