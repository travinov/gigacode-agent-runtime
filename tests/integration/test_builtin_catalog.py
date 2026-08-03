from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from gigacode_agent_runtime.agent_catalog import AgentProfileCatalog
from gigacode_agent_runtime.catalog import (
    builtin_scenarios_dir,
    create_scenario_catalog,
)
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.plan_compiler import compile_plan
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from tests.helpers.scheduler import scheduler_config


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_all_builtin_scenarios_validate_but_require_model_configuration(
    tmp_path: Path,
) -> None:
    config = scheduler_config(tmp_path)
    catalog = create_scenario_catalog(config)
    entries = catalog.discover()

    assert set(entries) == {
        "mixed",
        "parallel",
        "review-repair-loop",
        "sequential",
    }
    for entry in entries.values():
        assert entry.scenario.source.level == "builtin"
        with pytest.raises(AgentRuntimeError) as captured:
            compile_plan(
                entry.scenario,
                config,
                inputs={"task": "catalog smoke"},
                workspace=tmp_path,
            )
        assert captured.value.code is ErrorCode.MODEL_NOT_ALLOWED
        assert captured.value.details["placeholder"] is True


def test_project_override_does_not_modify_builtin_file(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path)
    builtin_path = builtin_scenarios_dir() / "sequential.yaml"
    before = _sha256(builtin_path)
    project = tmp_path / "project" / ".gigacode" / "scenarios"
    project.mkdir(parents=True)
    overridden = (builtin_path).read_text(encoding="utf-8").replace(
        "Sequential creator and reviewer",
        "Project sequential override",
    )
    (project / "sequential.yaml").write_text(overridden, encoding="utf-8")

    catalog = create_scenario_catalog(
        config,
        project_dir=project,
        workspace_root=tmp_path / "project",
    )
    selected = catalog.load("sequential")

    assert selected.source.level == "project"
    assert _sha256(builtin_path) == before
    assert load_scenario_file(builtin_path, level="builtin").source.level == "builtin"


def test_repository_examples_cover_builtin_and_agent_ref_scenarios(tmp_path: Path) -> None:
    examples_root = Path(__file__).parents[2] / "examples"
    examples = examples_root / "scenarios"
    example_names = {
        load_scenario_file(
            path,
            agent_catalog=AgentProfileCatalog(examples_root / "agents"),
        ).name
        for path in examples.glob("*.yaml")
    }
    builtin_names = set(create_scenario_catalog(scheduler_config(tmp_path)).discover())

    assert builtin_names <= example_names
    assert example_names - builtin_names == {"agent-ref"}
