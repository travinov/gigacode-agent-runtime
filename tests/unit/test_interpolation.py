from __future__ import annotations

import pytest

from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.interpolation import interpolate, validate_template


def test_only_declared_namespaces_are_allowed() -> None:
    validate_template(
        "${inputs.task} ${steps.analyze.output.summary} ${run.id} ${workspace.root}"
    )

    with pytest.raises(AgentRuntimeError) as captured:
        validate_template("${environment.SECRET}")

    assert captured.value.code is ErrorCode.SCENARIO_INVALID


def test_shell_substitution_is_plain_text() -> None:
    rendered = interpolate("Keep $(touch /tmp/nope) literal", lambda reference: reference)

    assert rendered == "Keep $(touch /tmp/nope) literal"


def test_interpolation_is_not_applied_twice() -> None:
    rendered = interpolate("${inputs.task}", lambda reference: "${environment.SECRET}")

    assert rendered == "${environment.SECRET}"


def test_whole_reference_preserves_structured_value() -> None:
    value = {"approved": True}

    rendered = interpolate("${steps.review.output}", lambda reference: value)

    assert rendered is value


def test_embedded_structured_value_uses_canonical_json() -> None:
    rendered = interpolate(
        "Review: ${steps.review.output}",
        lambda reference: {"approved": True},
    )

    assert rendered == 'Review: {"approved":true}'
