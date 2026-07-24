"""Clean-stdout local stdio MCP server."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .mcp_tools import AdapterFactory, McpToolService

TOOL_NAMES = (
    "list_scenarios",
    "describe_scenario",
    "validate_scenario",
    "plan_scenario",
    "diagnose_runtime",
    "start_run",
    "get_run_status",
    "get_run_events",
    "get_run_result",
    "get_run_artifacts",
    "provide_input",
    "approve_run",
    "pause_run",
    "resume_run",
    "cancel_run",
    "open_dashboard",
)


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

    server.tool(name="list_scenarios", structured_output=True)(
        tools.list_scenarios
    )
    server.tool(name="describe_scenario", structured_output=True)(
        tools.describe_scenario
    )
    server.tool(name="validate_scenario", structured_output=True)(
        tools.validate_scenario
    )
    server.tool(name="plan_scenario", structured_output=True)(
        tools.plan_scenario
    )
    server.tool(name="diagnose_runtime", structured_output=True)(
        tools.diagnose_runtime
    )
    server.tool(name="start_run", structured_output=True)(tools.start_run)
    server.tool(name="get_run_status", structured_output=True)(
        tools.get_run_status
    )
    server.tool(name="get_run_events", structured_output=True)(
        tools.get_run_events
    )
    server.tool(name="get_run_result", structured_output=True)(
        tools.get_run_result
    )
    server.tool(name="get_run_artifacts", structured_output=True)(
        tools.get_run_artifacts
    )
    server.tool(name="provide_input", structured_output=True)(
        tools.provide_input
    )
    server.tool(name="approve_run", structured_output=True)(tools.approve_run)
    server.tool(name="pause_run", structured_output=True)(tools.pause_run)
    server.tool(name="resume_run", structured_output=True)(tools.resume_run)
    server.tool(name="cancel_run", structured_output=True)(tools.cancel_run)
    server.tool(name="open_dashboard", structured_output=True)(
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
