"""Typed declarative condition evaluation without arbitrary code execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from .errors import AgentRuntimeError, ErrorCode
from .interpolation import interpolate


def _condition_error(message: str, *, operator: str) -> AgentRuntimeError:
    return AgentRuntimeError(
        ErrorCode.CONDITION_ERROR,
        message,
        details={"operator": operator},
    )


def _same_type(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return True
    return type(left) is type(right)


def _ordered_result(
    left: object,
    right: object,
    *,
    operator: str,
) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        if operator == "lt":
            return left < right
        if operator == "lte":
            return left <= right
        if operator == "gt":
            return left > right
        return left >= right
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        if operator == "lt":
            return left < right
        if operator == "lte":
            return left <= right
        if operator == "gt":
            return left > right
        return left >= right
    raise _condition_error(
        f"Operator {operator} requires two numbers or two strings",
        operator=operator,
    )


def _contains(container: object, value: object) -> bool:
    if isinstance(container, str):
        if not isinstance(value, str):
            raise _condition_error(
                "String contains requires a string value",
                operator="contains",
            )
        return value in container
    if isinstance(container, Mapping):
        return value in container
    if isinstance(container, Sequence) and not isinstance(container, (str, bytes)):
        return value in container
    raise _condition_error(
        "Contains requires a string, array, or object reference",
        operator="contains",
    )


def evaluate_condition(
    condition: Mapping[str, object],
    resolver: Callable[[str], object],
) -> bool:
    if "all" in condition:
        values = condition["all"]
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise _condition_error("all requires an array", operator="all")
        return all(
            evaluate_condition(item, resolver)
            for item in values
            if isinstance(item, Mapping)
        ) and all(isinstance(item, Mapping) for item in values)
    if "any" in condition:
        values = condition["any"]
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise _condition_error("any requires an array", operator="any")
        return any(
            evaluate_condition(item, resolver)
            for item in values
            if isinstance(item, Mapping)
        )
    if "not" in condition:
        nested = condition["not"]
        if not isinstance(nested, Mapping):
            raise _condition_error("not requires a condition", operator="not")
        return not evaluate_condition(nested, resolver)

    reference = condition.get("ref")
    operator = condition.get("op")
    if not isinstance(reference, str) or not isinstance(operator, str):
        raise _condition_error(
            "Simple condition requires string ref and op",
            operator=str(operator),
        )
    if not reference.startswith("${") or not reference.endswith("}"):
        raise _condition_error(
            "Condition ref must be one interpolation reference",
            operator=operator,
        )
    try:
        left = interpolate(reference, resolver)
        exists = True
    except (AgentRuntimeError, LookupError):
        if operator != "exists":
            raise
        left = None
        exists = False

    if operator == "exists":
        expected = condition.get("value", True)
        if not isinstance(expected, bool):
            raise _condition_error(
                "exists value must be boolean",
                operator=operator,
            )
        return exists is expected

    if "value" not in condition:
        raise _condition_error(
            f"Operator {operator} requires value",
            operator=operator,
        )
    right = condition["value"]
    if operator in {"eq", "ne"}:
        if not _same_type(left, right):
            raise _condition_error(
                f"Operator {operator} requires compatible operand types",
                operator=operator,
            )
        return (left == right) if operator == "eq" else (left != right)
    if operator in {"lt", "lte", "gt", "gte"}:
        return _ordered_result(left, right, operator=operator)
    if operator == "contains":
        return _contains(left, right)
    raise _condition_error(f"Unsupported condition operator: {operator}", operator=operator)
