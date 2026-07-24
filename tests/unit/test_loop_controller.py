from __future__ import annotations

from pathlib import Path

from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.domain import LoopStepDefinition
from gigacode_agent_runtime.plan_compiler import compile_plan
from gigacode_agent_runtime.scenario_loader import load_scenario_file

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


def test_loop_is_compiled_as_bounded_inner_dag(tmp_path: Path) -> None:
    plan = compile_plan(
        load_scenario_file(SCENARIOS / "full-access-loop.yaml"),
        load_config(tmp_path / "missing.yaml", home=tmp_path / "home"),
        inputs={},
        workspace=tmp_path,
    )
    loop = plan.steps[0]

    assert isinstance(loop, LoopStepDefinition)
    assert loop.waves == (("review",), ("repair",))
    assert loop.max_iterations == 3
