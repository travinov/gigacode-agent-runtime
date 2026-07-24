"""Command line interface for shell, CI, and emergency runtime control."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections.abc import Mapping, Sequence
from functools import partial
from pathlib import Path

import anyio

from .adapter_factory import create_gigacode_adapter
from .cli_format import (
    EXIT_INTERNAL,
    emit,
    emit_error,
    state_exit_code,
)
from .config import EffectiveConfig, load_config
from .domain import RunStatus
from .errors import AgentRuntimeError, ErrorCode
from .event_log import EventLog, event_to_document
from .mcp_server import create_mcp_server
from .mcp_tools import McpToolService
from .plan_compiler import compile_plan, execution_plan_to_document
from .runtime_service import RuntimeService
from .scenario_loader import LoadedScenario, ScenarioCatalog, load_scenario_file
from .scheduler import DagScheduler
from .state_store import StateStore, run_state_to_document
from .version import __version__

_TERMINAL = {
    RunStatus.COMPLETED,
    RunStatus.COMPLETED_BEST_EFFORT,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.INTERRUPTED,
    RunStatus.PAUSED,
    RunStatus.WAITING_FOR_APPROVAL,
}


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", dest="as_json")


def _add_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="KEY=VALUE",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-runtime",
        description="Local multi-agent runtime for GigaCode CLI",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    diagnose = subparsers.add_parser("diagnose")
    _add_json(diagnose)

    scenarios = subparsers.add_parser("scenarios")
    scenarios_sub = scenarios.add_subparsers(dest="scenarios_command", required=True)
    scenarios_list = scenarios_sub.add_parser("list")
    _add_json(scenarios_list)

    scenario = subparsers.add_parser("scenario")
    scenario_sub = scenario.add_subparsers(dest="scenario_command", required=True)
    validate = scenario_sub.add_parser("validate")
    validate.add_argument("file", type=Path)
    _add_json(validate)
    plan = scenario_sub.add_parser("plan")
    plan.add_argument("file", type=Path)
    plan.add_argument("--workspace", type=Path, default=Path.cwd())
    _add_inputs(plan)
    _add_json(plan)

    run = subparsers.add_parser("run")
    run.add_argument("target")
    run.add_argument("--workspace", type=Path, default=Path.cwd())
    run.add_argument("--idempotency-key")
    _add_inputs(run)
    _add_json(run)

    status = subparsers.add_parser("status")
    status.add_argument("run_id")
    _add_json(status)

    events = subparsers.add_parser("events")
    events.add_argument("run_id")
    events.add_argument("--after", type=int, default=0)
    events.add_argument("--limit", type=int, default=100)
    events.add_argument("--follow", action="store_true")
    _add_json(events)

    result = subparsers.add_parser("result")
    result.add_argument("run_id")
    _add_json(result)

    resume = subparsers.add_parser("resume")
    resume.add_argument("run_id")
    _add_json(resume)

    cancel = subparsers.add_parser("cancel")
    cancel.add_argument("run_id")
    _add_json(cancel)

    dashboard = subparsers.add_parser("dashboard")
    dashboard.add_argument("run_id", nargs="?")
    dashboard.add_argument("--open", action="store_true", dest="open_browser")
    _add_json(dashboard)

    mcp_serve = subparsers.add_parser("mcp-serve")
    _add_json(mcp_serve)
    return parser


def _parse_inputs(values: Sequence[str]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for item in values:
        if "=" not in item:
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                f"Input must use KEY=VALUE syntax: {item}",
            )
        name, raw = item.split("=", 1)
        if not name or name in parsed:
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                f"Input key is empty or duplicated: {name}",
            )
        try:
            value: object = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        parsed[name] = value
    return parsed


def _catalog(config: EffectiveConfig) -> ScenarioCatalog:
    project = Path.cwd() / ".gigacode" / "scenarios"
    return ScenarioCatalog(
        user_dir=config.paths.user_scenarios,
        project_dir=project,
        workspace_root=Path.cwd(),
    )


def _target_scenario(target: str, config: EffectiveConfig) -> LoadedScenario:
    path = Path(target)
    if path.is_file():
        return load_scenario_file(path)
    return _catalog(config).load(target)


async def _diagnose(config: EffectiveConfig) -> dict[str, object]:
    adapter = create_gigacode_adapter(config)
    capabilities = await adapter.detect_capabilities()
    return {
        "runtime_version": __version__,
        "python": sys.version.split()[0],
        "capabilities": capabilities.to_snapshot(),
    }


async def _run_foreground(
    config: EffectiveConfig,
    scenario: LoadedScenario,
    *,
    inputs: Mapping[str, object],
    workspace: Path,
    idempotency_key: str | None = None,
) -> tuple[dict[str, object], int]:
    prepared = RuntimeService(config).start_run(
        scenario,
        inputs=inputs,
        workspace=workspace,
        idempotency_key=idempotency_key,
    )
    if prepared.state.status is RunStatus.PLANNED:
        scheduled = await DagScheduler(
            prepared.config,
            create_gigacode_adapter(prepared.config),
        ).run(prepared)
        state = scheduled.state
    else:
        state = prepared.state
    return run_state_to_document(state), state_exit_code(state.status)


async def _resume_foreground(
    config: EffectiveConfig,
    run_id: str,
) -> tuple[dict[str, object], int]:
    prepared = RuntimeService(config).prepare_resume(run_id)
    scheduled = await DagScheduler(
        prepared.config,
        create_gigacode_adapter(prepared.config),
    ).run(prepared)
    return (
        run_state_to_document(scheduled.state),
        state_exit_code(scheduled.state.status),
    )


async def _follow_events(
    config: EffectiveConfig,
    run_id: str,
    *,
    after: int,
    limit: int,
    as_json: bool,
) -> int:
    states = StateStore(config.paths.runs)
    run_dir = states.run_dir(run_id)
    events = EventLog(run_dir, run_id=run_id)
    cursor = after
    while True:
        page = events.read(after=cursor, limit=limit)
        for event in page.events:
            document = event_to_document(event)
            emit(
                document,
                as_json=as_json,
                human=f"{event.event_id} {event.type} {dict(event.payload)}",
            )
        cursor = page.next_cursor
        state = states.read(run_id)
        if state.status in _TERMINAL and not page.has_more:
            return state_exit_code(state.status)
        await anyio.sleep(0.25)


async def _dashboard_foreground(
    config: EffectiveConfig,
    run_id: str | None,
    *,
    open_browser: bool,
    as_json: bool,
) -> int:
    tools = McpToolService(config)
    async with tools:
        response = await tools.open_dashboard(run_id)
        if response["ok"] is not True:
            raw = response["error"]
            assert isinstance(raw, dict)
            raise AgentRuntimeError(
                ErrorCode(str(raw["code"])),
                str(raw["message"]),
                details=(
                    raw["details"] if isinstance(raw.get("details"), dict) else {}
                ),
            )
        data = response["data"]
        assert isinstance(data, dict)
        url = str(data["url"])
        emit({"url": url}, as_json=as_json, human=url)
        if open_browser:
            webbrowser.open(url)
        await anyio.sleep_forever()
    return 0


def _cancel_inactive(config: EffectiveConfig, run_id: str) -> dict[str, object]:
    states = StateStore(config.paths.runs)
    state = states.read(run_id)
    if state.status is RunStatus.RUNNING:
        raise AgentRuntimeError(
            ErrorCode.CAPABILITY_UNAVAILABLE,
            "A foreground CLI cannot cancel a run owned by another process",
            details={"run_id": run_id},
        )
    if state.status not in {
        RunStatus.PLANNED,
        RunStatus.PAUSED,
        RunStatus.INTERRUPTED,
        RunStatus.WAITING_FOR_APPROVAL,
    }:
        raise AgentRuntimeError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Run cannot be cancelled from {state.status.value}",
            details={"run_id": run_id, "status": state.status.value},
        )
    return run_state_to_document(
        states.finish(
            run_id,
            RunStatus.CANCELLED,
            error={"code": "CANCELLED", "message": "Run was cancelled"},
        )
    )


def _execute(arguments: argparse.Namespace, config: EffectiveConfig) -> int:
    as_json = bool(getattr(arguments, "as_json", False))
    if arguments.command == "diagnose":
        document = anyio.run(_diagnose, config)
        emit(document, as_json=as_json)
        return 0
    if arguments.command == "scenarios":
        entries = [
            {
                "name": entry.name,
                "title": entry.title,
                "source": entry.source.level,
            }
            for entry in _catalog(config).discover().values()
        ]
        emit({"scenarios": entries}, as_json=as_json)
        return 0
    if arguments.command == "scenario":
        scenario = load_scenario_file(arguments.file)
        if arguments.scenario_command == "validate":
            document = {"valid": True, "name": scenario.name}
        else:
            document = execution_plan_to_document(
                compile_plan(
                    scenario,
                    config,
                    inputs=_parse_inputs(arguments.input),
                    workspace=arguments.workspace,
                )
            )
        emit(document, as_json=as_json)
        return 0
    if arguments.command == "run":
        document, exit_code = anyio.run(
            partial(
                _run_foreground,
                inputs=_parse_inputs(arguments.input),
                workspace=arguments.workspace,
                idempotency_key=arguments.idempotency_key,
            ),
            config,
            _target_scenario(arguments.target, config),
        )
        emit(
            document,
            as_json=as_json,
            human=f"{document['run_id']}: {document['status']}",
        )
        return exit_code
    if arguments.command == "status":
        state = StateStore(config.paths.runs).read(arguments.run_id)
        document = run_state_to_document(state)
        emit(
            document,
            as_json=as_json,
            human=f"{state.run_id}: {state.status.value}",
        )
        return state_exit_code(state.status)
    if arguments.command == "events":
        if arguments.follow:
            return anyio.run(
                partial(
                    _follow_events,
                    after=arguments.after,
                    limit=arguments.limit,
                    as_json=as_json,
                ),
                config,
                arguments.run_id,
            )
        states = StateStore(config.paths.runs)
        states.read(arguments.run_id)
        page = EventLog(
            states.run_dir(arguments.run_id),
            run_id=arguments.run_id,
        ).read(after=arguments.after, limit=arguments.limit)
        document = {
            "events": [event_to_document(event) for event in page.events],
            "next_cursor": page.next_cursor,
            "has_more": page.has_more,
        }
        emit(document, as_json=as_json)
        return 0
    if arguments.command == "result":
        document = RuntimeService(config).get_result(arguments.run_id)
        emit(document, as_json=as_json)
        return state_exit_code(
            StateStore(config.paths.runs).read(arguments.run_id).status
        )
    if arguments.command == "resume":
        document, exit_code = anyio.run(
            _resume_foreground,
            config,
            arguments.run_id,
        )
        emit(document, as_json=as_json)
        return exit_code
    if arguments.command == "cancel":
        document = _cancel_inactive(config, arguments.run_id)
        emit(document, as_json=as_json)
        return state_exit_code(RunStatus(str(document["status"])))
    if arguments.command == "dashboard":
        return anyio.run(
            partial(
                _dashboard_foreground,
                open_browser=arguments.open_browser,
                as_json=as_json,
            ),
            config,
            arguments.run_id,
        )
    if arguments.command == "mcp-serve":
        tools = McpToolService(
            config,
            project_scenarios=Path.cwd() / ".gigacode" / "scenarios",
        )
        create_mcp_server(tools).run(transport="stdio")
        return 0
    raise AgentRuntimeError(
        ErrorCode.CONFIG_INVALID,
        f"Unknown command: {arguments.command}",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    as_json = bool(getattr(arguments, "as_json", False))
    try:
        config = load_config(arguments.config)
        return _execute(arguments, config)
    except AgentRuntimeError as error:
        return emit_error(error, as_json=as_json)
    except KeyboardInterrupt:
        return 5
    except Exception:
        if as_json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": ErrorCode.INTERNAL_ERROR.value,
                            "message": "Internal runtime error",
                            "details": {},
                            "retryable": False,
                        },
                    },
                    sort_keys=True,
                )
            )
        else:
            print("INTERNAL_ERROR: Internal runtime error", file=sys.stderr)
        return EXIT_INTERNAL
