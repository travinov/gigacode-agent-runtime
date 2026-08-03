from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.plan_compiler import (
    compile_plan,
    execution_plan_from_document,
    execution_plan_to_document,
)
from gigacode_agent_runtime.scenario_loader import load_scenario_file

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


def test_execution_plan_snapshot_round_trips_for_resume(tmp_path: Path) -> None:
    original = compile_plan(
        load_scenario_file(SCENARIOS / "full-access-loop.yaml"),
        load_config(tmp_path / "missing.yaml", home=tmp_path / "home"),
        inputs={},
        workspace=tmp_path,
    )

    restored = execution_plan_from_document(execution_plan_to_document(original))

    assert restored.plan_hash == original.plan_hash
    assert execution_plan_to_document(restored) == execution_plan_to_document(original)


def test_tampered_execution_plan_snapshot_is_rejected(tmp_path: Path) -> None:
    original = compile_plan(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        load_config(tmp_path / "missing.yaml", home=tmp_path / "home"),
        inputs={},
        workspace=tmp_path,
    )
    document = execution_plan_to_document(original)
    document["result_reference"] = "${steps.create.output}"

    with pytest.raises(AgentRuntimeError) as captured:
        execution_plan_from_document(document)

    assert captured.value.code is ErrorCode.STATE_CORRUPTED
