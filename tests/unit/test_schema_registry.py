from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.schema_registry import (
    SCHEMA_NAMES,
    load_schema,
    validate_document,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_bundled_schema_is_a_valid_draft_2020_12_schema(schema_name: str) -> None:
    schema = load_schema(schema_name)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_minimal_scenario_validates() -> None:
    document = yaml.safe_load((FIXTURES / "minimal-valid.yaml").read_text())

    validate_document("scenario-v1", document)


def test_unknown_key_has_stable_error_path() -> None:
    document = yaml.safe_load((FIXTURES / "invalid-unknown-key.yaml").read_text())

    with pytest.raises(AgentRuntimeError) as captured:
        validate_document("scenario-v1", document)

    assert captured.value.code is ErrorCode.SCENARIO_INVALID
    assert captured.value.details["path"] == "/metadata"
    assert "unsupported" in captured.value.message


def test_schema_result_is_not_shared_mutable_state() -> None:
    first = load_schema("scenario-v1")
    first["title"] = "mutated"

    second = load_schema("scenario-v1")

    assert second["title"] != "mutated"


def test_unknown_schema_name_is_a_typed_error() -> None:
    with pytest.raises(AgentRuntimeError) as captured:
        load_schema("missing-v1")

    assert captured.value.code is ErrorCode.SCHEMA_NOT_FOUND
