from __future__ import annotations

import pytest

from gigacode_agent_runtime.dag import topological_waves
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode


def test_topological_waves_support_fan_out_and_fan_in() -> None:
    dependencies = {
        "source": (),
        "left": ("source",),
        "right": ("source",),
        "join": ("left", "right"),
    }

    assert topological_waves(dependencies) == (
        ("source",),
        ("left", "right"),
        ("join",),
    )


def test_unknown_dependency_is_rejected() -> None:
    with pytest.raises(AgentRuntimeError) as captured:
        topological_waves({"step": ("missing",)})

    assert captured.value.code is ErrorCode.SCENARIO_INVALID
    assert captured.value.details["dependency"] == "missing"


def test_cycle_is_reported_with_participating_nodes() -> None:
    with pytest.raises(AgentRuntimeError) as captured:
        topological_waves({"first": ("second",), "second": ("first",)})

    assert captured.value.code is ErrorCode.SCENARIO_INVALID
    assert set(captured.value.details["cycle"]) == {"first", "second"}
