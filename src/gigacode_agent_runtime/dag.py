"""Deterministic dependency validation and wave construction."""

from __future__ import annotations

from collections.abc import Mapping

from .errors import AgentRuntimeError, ErrorCode


def _find_cycle(dependencies: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> tuple[str, ...] | None:
        if node in visited:
            return None
        if node in visiting:
            start = stack.index(node)
            return tuple(stack[start:])
        visiting.add(node)
        stack.append(node)
        for dependency in dependencies[node]:
            cycle = visit(dependency)
            if cycle is not None:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in sorted(dependencies):
        cycle = visit(node)
        if cycle is not None:
            return cycle
    return ()


def topological_waves(
    dependencies: Mapping[str, tuple[str, ...]],
) -> tuple[tuple[str, ...], ...]:
    nodes = set(dependencies)
    for node, required in dependencies.items():
        for dependency in required:
            if dependency not in nodes:
                raise AgentRuntimeError(
                    ErrorCode.SCENARIO_INVALID,
                    f"Step '{node}' depends on unknown step '{dependency}'",
                    details={"step": node, "dependency": dependency},
                )

    remaining = {node: set(required) for node, required in dependencies.items()}
    completed: set[str] = set()
    waves: list[tuple[str, ...]] = []
    while remaining:
        ready = tuple(
            sorted(node for node, required in remaining.items() if required <= completed)
        )
        if not ready:
            cycle = _find_cycle(dependencies)
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                "Scenario dependency graph contains a cycle",
                details={"cycle": list(cycle)},
            )
        waves.append(ready)
        completed.update(ready)
        for node in ready:
            del remaining[node]
    return tuple(waves)
