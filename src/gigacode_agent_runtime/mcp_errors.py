"""Stable public result envelopes for MCP tools."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from .errors import AgentRuntimeError, ErrorCode


def success(data: object) -> dict[str, object]:
    return {"ok": True, "data": data}


def failure(error: AgentRuntimeError) -> dict[str, object]:
    return {"ok": False, "error": error.to_dict()}


async def public_result(
    operation: Callable[[], object | Awaitable[object]],
) -> dict[str, object]:
    try:
        result = operation()
        if inspect.isawaitable(result):
            result = await result
        return success(result)
    except AgentRuntimeError as error:
        return failure(error)
    except Exception:
        return failure(
            AgentRuntimeError(
                ErrorCode.INTERNAL_ERROR,
                "Internal runtime error",
            )
        )
