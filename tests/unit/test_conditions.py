from __future__ import annotations

import pytest

from gigacode_agent_runtime.conditions import evaluate_condition
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode


def _resolver(values):
    def resolve(reference: str):
        current = values
        for part in reference.split("."):
            current = current[part]
        return current

    return resolve


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ({"ref": "${inputs.value}", "op": "eq", "value": 3}, True),
        ({"ref": "${inputs.value}", "op": "ne", "value": 4}, True),
        ({"ref": "${inputs.value}", "op": "lt", "value": 4}, True),
        ({"ref": "${inputs.value}", "op": "lte", "value": 3}, True),
        ({"ref": "${inputs.value}", "op": "gt", "value": 2}, True),
        ({"ref": "${inputs.value}", "op": "gte", "value": 3}, True),
        ({"ref": "${inputs.items}", "op": "contains", "value": "b"}, True),
        ({"ref": "${inputs.missing}", "op": "exists", "value": False}, True),
        (
            {
                "all": [
                    {"ref": "${inputs.value}", "op": "eq", "value": 3},
                    {"not": {"ref": "${inputs.value}", "op": "eq", "value": 2}},
                ]
            },
            True,
        ),
        (
            {
                "any": [
                    {"ref": "${inputs.value}", "op": "eq", "value": 2},
                    {"ref": "${inputs.value}", "op": "eq", "value": 3},
                ]
            },
            True,
        ),
    ],
)
def test_typed_condition_operators(condition, expected: bool) -> None:
    assert evaluate_condition(
        condition,
        _resolver({"inputs": {"value": 3, "items": ["a", "b"]}}),
    ) is expected


def test_condition_type_mismatch_is_typed_error() -> None:
    with pytest.raises(AgentRuntimeError) as captured:
        evaluate_condition(
            {"ref": "${inputs.value}", "op": "lt", "value": "3"},
            _resolver({"inputs": {"value": 3}}),
        )

    assert captured.value.code is ErrorCode.CONDITION_ERROR


def test_condition_never_evaluates_code() -> None:
    with pytest.raises(AgentRuntimeError) as captured:
        evaluate_condition(
            {"ref": "__import__('os').system('false')", "op": "eq", "value": 0},
            _resolver({}),
        )

    assert captured.value.code is ErrorCode.CONDITION_ERROR
