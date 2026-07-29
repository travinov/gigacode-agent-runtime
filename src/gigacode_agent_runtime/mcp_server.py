"""Clean-stdout local stdio MCP server."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .mcp_tools import AdapterFactory, McpToolService

TOOL_DESCRIPTIONS = {
    "list_scenarios": (
        "List the built-in, user, and project agent scenarios available to run."
    ),
    "describe_scenario": (
        "Return metadata, inputs, agents, and step names for one scenario."
    ),
    "validate_scenario": (
        "Validate a named or inline agent scenario without executing it."
    ),
    "plan_scenario": (
        "Compile a scenario into an immutable execution plan for a workspace."
    ),
    "diagnose_runtime": (
        "Check runtime configuration and local GigaCode CLI readiness."
    ),
    "start_run": "Create and asynchronously start an agent scenario run.",
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
            "GigaCode/Qwen agent scenarios locally."
        ),
        log_level="ERROR",
        lifespan=lifespan,
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
        tools.validate_scenario
    )
    server.tool(
        name="plan_scenario",
        description=TOOL_DESCRIPTIONS["plan_scenario"],
        structured_output=True,
    )(
        tools.plan_scenario
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
    )(tools.start_run)
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
