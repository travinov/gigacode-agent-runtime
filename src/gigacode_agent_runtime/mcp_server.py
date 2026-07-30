"""Clean-stdout local stdio MCP server."""

from __future__ import annotations

import math
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, cast

import yaml
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .config import load_config
from .errors import AgentRuntimeError, ErrorCode
from .mcp_errors import failure
from .mcp_tools import AdapterFactory, McpToolService
from .yaml_loader import safe_load

_MAX_WIRE_YAML_BYTES = 2 * 1024 * 1024
_MAX_WIRE_VALUE_NODES = 100_000

TOOL_DESCRIPTIONS = {
    "list_scenarios": (
        "List the built-in, user, and project agent scenarios available to run."
    ),
    "describe_scenario": (
        "Return the complete declarative contract for one named scenario, "
        "including agents, full step definitions, dependencies, output schemas, "
        "and result."
    ),
    "validate_scenario": (
        "Validate a named scenario or inline_scenario_yaml without executing it."
    ),
    "plan_scenario": (
        "Compile a scenario into an immutable execution plan. Pass scenario "
        "values through inputs_yaml as YAML mapping text, never as a JSON object "
        "or JSON-encoded string."
    ),
    "diagnose_runtime": (
        "Check runtime configuration and local GigaCode CLI readiness."
    ),
    "start_run": (
        "Create and asynchronously start an agent scenario run. Pass scenario "
        "values through inputs_yaml as YAML mapping text."
    ),
    "get_run_status": "Return the durable status and step states for a run.",
    "get_run_events": "Read a bounded page of durable events for a run.",
    "get_run_result": "Return the terminal result of a completed run.",
    "get_run_artifacts": "List a bounded page of artifact metadata for a run.",
    "provide_input": "Provide a value requested by a waiting run input gate.",
    "approve_run": (
        "Approve an exact immutable run plan for a protected permission gate."
    ),
    "pause_run": "Request a safe pause after the active run wave finishes.",
    "resume_run": "Resume a paused, interrupted, or waiting agent run.",
    "cancel_run": "Cancel an agent run and terminate its active processes.",
    "open_dashboard": "Open the authenticated local monitoring dashboard URL.",
}
TOOL_NAMES = tuple(TOOL_DESCRIPTIONS)


def _assert_json_compatible(value: object) -> None:
    pending = [value]
    visited = 0
    while pending:
        current = pending.pop()
        visited += 1
        if visited > _MAX_WIRE_VALUE_NODES:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                "inputs_yaml contains too many values",
                details={"parameter": "inputs_yaml"},
            )
        if current is None or isinstance(current, (bool, int, str)):
            continue
        if isinstance(current, float):
            if math.isfinite(current):
                continue
        elif isinstance(current, list):
            pending.extend(current)
            continue
        elif isinstance(current, dict) and all(
            isinstance(key, str) for key in current
        ):
            pending.extend(current.values())
            continue
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            "inputs_yaml must contain only JSON-compatible values",
            details={"parameter": "inputs_yaml"},
        )


def _inputs_from_yaml(inputs_yaml: str | None) -> dict[str, Any]:
    if inputs_yaml is None or not inputs_yaml.strip():
        return {}
    if len(inputs_yaml.encode("utf-8")) > _MAX_WIRE_YAML_BYTES:
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            "inputs_yaml exceeds 2 MiB",
            details={"parameter": "inputs_yaml"},
        )
    try:
        loaded = safe_load(inputs_yaml)
    except yaml.YAMLError as exc:
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            "inputs_yaml is not valid YAML",
            details={"parameter": "inputs_yaml"},
        ) from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            "inputs_yaml must decode to a mapping with string keys",
            details={"parameter": "inputs_yaml"},
        )
    _assert_json_compatible(loaded)
    return cast(dict[str, Any], loaded)


def create_mcp_server(
    tools: McpToolService,
) -> FastMCP[None]:
    @asynccontextmanager
    async def lifespan(_server: FastMCP[None]) -> AsyncIterator[None]:
        async with tools:
            yield None

    server: FastMCP[None] = FastMCP(
        "GigaCode Agent Runtime",
        instructions=(
            "Run declarative sequential, parallel, mixed, and looped "
            "GigaCode/Qwen agent scenarios locally. For plan_scenario and "
            "start_run, pass inputs_yaml as YAML mapping text such as "
            "'task: inspect the runtime'; never JSON-stringify a nested object. "
            "For inline scenarios, pass YAML through inline_scenario_yaml. "
            "Do not fall back to Shell when an MCP call fails."
        ),
        log_level="ERROR",
        lifespan=lifespan,
    )

    async def validate_scenario_tool(
        scenario_name: Annotated[
            str | None,
            Field(
                description=(
                    "Catalog scenario name. Provide exactly one of scenario_name "
                    "or inline_scenario_yaml."
                )
            ),
        ] = None,
        inline_scenario_yaml: Annotated[
            str | None,
            Field(
                description=(
                    "Complete scenario-v1 YAML text. Use YAML beginning with "
                    "schema_version, not JSON text. Provide exactly one scenario "
                    "source."
                )
            ),
        ] = None,
    ) -> dict[str, object]:
        return await tools.validate_scenario(
            scenario_name=scenario_name,
            inline_scenario=inline_scenario_yaml,
        )

    async def plan_scenario_tool(
        workspace: Annotated[
            str,
            Field(description="Existing absolute or user-resolvable workspace path."),
        ],
        scenario_name: Annotated[
            str | None,
            Field(
                description=(
                    "Catalog scenario name. Provide exactly one of scenario_name "
                    "or inline_scenario_yaml."
                )
            ),
        ] = None,
        inline_scenario_yaml: Annotated[
            str | None,
            Field(
                description=(
                    "Complete scenario-v1 YAML text. Use YAML, not JSON text."
                )
            ),
        ] = None,
        inputs_yaml: Annotated[
            str | None,
            Field(
                description=(
                    "Scenario input values as YAML mapping text, for example "
                    "'task: Check the local MCP runtime'. Do not pass a JSON "
                    "object or a JSON-encoded string."
                )
            ),
        ] = None,
    ) -> dict[str, object]:
        try:
            inputs = _inputs_from_yaml(inputs_yaml)
        except AgentRuntimeError as error:
            return failure(error)
        return await tools.plan_scenario(
            workspace=workspace,
            scenario_name=scenario_name,
            inline_scenario=inline_scenario_yaml,
            inputs=inputs,
        )

    async def start_run_tool(
        workspace: Annotated[
            str,
            Field(description="Existing absolute or user-resolvable workspace path."),
        ],
        scenario_name: Annotated[
            str | None,
            Field(
                description=(
                    "Catalog scenario name. Provide exactly one of scenario_name "
                    "or inline_scenario_yaml."
                )
            ),
        ] = None,
        inline_scenario_yaml: Annotated[
            str | None,
            Field(
                description=(
                    "Complete scenario-v1 YAML text. Use YAML, not JSON text."
                )
            ),
        ] = None,
        inputs_yaml: Annotated[
            str | None,
            Field(
                description=(
                    "Scenario input values as YAML mapping text, for example "
                    "'task: Check the local MCP runtime'. Do not pass a JSON "
                    "object or a JSON-encoded string."
                )
            ),
        ] = None,
        idempotency_key: Annotated[
            str | None,
            Field(
                description=(
                    "Stable retry key for this exact scenario, inputs, and "
                    "workspace. It is not a run_id."
                )
            ),
        ] = None,
    ) -> dict[str, object]:
        try:
            inputs = _inputs_from_yaml(inputs_yaml)
        except AgentRuntimeError as error:
            return failure(error)
        return await tools.start_run(
            workspace=workspace,
            scenario_name=scenario_name,
            inline_scenario=inline_scenario_yaml,
            inputs=inputs,
            idempotency_key=idempotency_key,
        )

    server.tool(
        name="list_scenarios",
        description=TOOL_DESCRIPTIONS["list_scenarios"],
        structured_output=True,
    )(tools.list_scenarios)
    server.tool(
        name="describe_scenario",
        description=TOOL_DESCRIPTIONS["describe_scenario"],
        structured_output=True,
    )(
        tools.describe_scenario
    )
    server.tool(
        name="validate_scenario",
        description=TOOL_DESCRIPTIONS["validate_scenario"],
        structured_output=True,
    )(
        validate_scenario_tool
    )
    server.tool(
        name="plan_scenario",
        description=TOOL_DESCRIPTIONS["plan_scenario"],
        structured_output=True,
    )(
        plan_scenario_tool
    )
    server.tool(
        name="diagnose_runtime",
        description=TOOL_DESCRIPTIONS["diagnose_runtime"],
        structured_output=True,
    )(
        tools.diagnose_runtime
    )
    server.tool(
        name="start_run",
        description=TOOL_DESCRIPTIONS["start_run"],
        structured_output=True,
    )(start_run_tool)
    server.tool(
        name="get_run_status",
        description=TOOL_DESCRIPTIONS["get_run_status"],
        structured_output=True,
    )(
        tools.get_run_status
    )
    server.tool(
        name="get_run_events",
        description=TOOL_DESCRIPTIONS["get_run_events"],
        structured_output=True,
    )(
        tools.get_run_events
    )
    server.tool(
        name="get_run_result",
        description=TOOL_DESCRIPTIONS["get_run_result"],
        structured_output=True,
    )(
        tools.get_run_result
    )
    server.tool(
        name="get_run_artifacts",
        description=TOOL_DESCRIPTIONS["get_run_artifacts"],
        structured_output=True,
    )(
        tools.get_run_artifacts
    )
    server.tool(
        name="provide_input",
        description=TOOL_DESCRIPTIONS["provide_input"],
        structured_output=True,
    )(
        tools.provide_input
    )
    server.tool(
        name="approve_run",
        description=TOOL_DESCRIPTIONS["approve_run"],
        structured_output=True,
    )(tools.approve_run)
    server.tool(
        name="pause_run",
        description=TOOL_DESCRIPTIONS["pause_run"],
        structured_output=True,
    )(tools.pause_run)
    server.tool(
        name="resume_run",
        description=TOOL_DESCRIPTIONS["resume_run"],
        structured_output=True,
    )(tools.resume_run)
    server.tool(
        name="cancel_run",
        description=TOOL_DESCRIPTIONS["cancel_run"],
        structured_output=True,
    )(tools.cancel_run)
    server.tool(
        name="open_dashboard",
        description=TOOL_DESCRIPTIONS["open_dashboard"],
        structured_output=True,
    )(
        tools.open_dashboard
    )
    return server


def build_default_server(
    *,
    adapter_factory: AdapterFactory | None = None,
) -> tuple[FastMCP[None], McpToolService]:
    config_value = os.environ.get("GIGACODE_AGENT_RUNTIME_CONFIG")
    config = load_config(Path(config_value) if config_value else None)
    project_value = os.environ.get("GIGACODE_AGENT_RUNTIME_PROJECT_SCENARIOS")
    project_scenarios = (
        Path(project_value)
        if project_value
        else Path.cwd() / ".gigacode" / "scenarios"
    )
    tools = McpToolService(
        config,
        project_scenarios=project_scenarios,
        adapter_factory=adapter_factory,
    )
    return create_mcp_server(tools), tools


def main() -> None:
    server, _tools = build_default_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
