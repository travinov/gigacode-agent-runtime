"""Load and validate versioned JSON Schemas."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from .errors import AgentRuntimeError, ErrorCode

SCHEMA_NAMES = (
    "config-v1",
    "scenario-v1",
    "execution-plan-v1",
    "run-state-v1",
    "run-event-v1",
)

_SCHEMA_FILENAMES = {name: f"{name}.schema.json" for name in SCHEMA_NAMES}


def _schema_error_code(schema_name: str) -> ErrorCode:
    if schema_name == "config-v1":
        return ErrorCode.CONFIG_INVALID
    if schema_name == "scenario-v1":
        return ErrorCode.SCENARIO_INVALID
    return ErrorCode.SCHEMA_INVALID


def _json_pointer(parts: list[object]) -> str:
    if not parts:
        return "/"
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded)


def _read_schema_text(filename: str) -> str:
    packaged = files("gigacode_agent_runtime").joinpath("_schemas", filename)
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")

    installed_schema = (
        Path(sys.prefix) / "share" / "gigacode-agent-runtime" / "schemas" / filename
    )
    if installed_schema.is_file():
        return installed_schema.read_text(encoding="utf-8")

    checkout_schema = Path(__file__).resolve().parents[2] / "schemas" / filename
    if checkout_schema.is_file():
        return checkout_schema.read_text(encoding="utf-8")

    raise AgentRuntimeError(
        ErrorCode.SCHEMA_NOT_FOUND,
        f"Bundled schema file is missing: {filename}",
        details={"filename": filename},
    )


@cache
def _load_schema_cached(schema_name: str) -> dict[str, Any]:
    filename = _SCHEMA_FILENAMES.get(schema_name)
    if filename is None:
        raise AgentRuntimeError(
            ErrorCode.SCHEMA_NOT_FOUND,
            f"Unknown schema: {schema_name}",
            details={"schema_name": schema_name},
        )

    try:
        parsed = cast(dict[str, Any], json.loads(_read_schema_text(filename)))
        Draft202012Validator.check_schema(parsed)
    except AgentRuntimeError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise AgentRuntimeError(
            ErrorCode.SCHEMA_INVALID,
            f"Bundled schema is invalid: {schema_name}",
            details={"schema_name": schema_name},
        ) from exc
    return parsed


def load_schema(schema_name: str) -> dict[str, Any]:
    """Return an isolated copy so callers cannot mutate the registry cache."""

    return deepcopy(_load_schema_cached(schema_name))


def validate_document(schema_name: str, document: object) -> None:
    """Validate a document and raise the first deterministic typed error."""

    validator = Draft202012Validator(_load_schema_cached(schema_name))
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            tuple(str(part) for part in error.absolute_schema_path),
            error.message,
        ),
    )
    if not errors:
        return

    error = errors[0]
    path = _json_pointer(list(error.absolute_path))
    raise AgentRuntimeError(
        _schema_error_code(schema_name),
        error.message,
        details={
            "path": path,
            "schema_path": _json_pointer(list(error.absolute_schema_path)),
            "validator": str(error.validator),
        },
    )
