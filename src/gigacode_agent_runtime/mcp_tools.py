"""MCP-facing application use cases with bounded, path-safe results."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, cast

import anyio

from .adapter_factory import create_gigacode_adapter
from .agent_catalog import AgentProfile
from .approval_store import ApprovalStore
from .catalog import create_agent_profile_catalog, create_scenario_catalog
from .config import EffectiveConfig
from .diagnostics import diagnose_runtime
from .domain import RunStatus
from .errors import AgentRuntimeError, ErrorCode
from .event_log import EventLog, event_to_document
from .hashing import sha256_digest
from .input_gates import InputGateStore
from .mcp_errors import public_result
from .plan_compiler import compile_plan, execution_plan_to_document
from .run_manager import RunManager
from .runtime_service import RuntimeService
from .scenario_loader import LoadedScenario, load_scenario_file
from .scheduler import DagScheduler
from .serialization import atomic_write_text
from .state_store import StateStore, run_state_to_document
from .step_runner import AgentAdapter

AdapterFactory = Callable[[], AgentAdapter]

if TYPE_CHECKING:
    from .web.server import LocalWebServer


class McpToolService:
    def __init__(
        self,
        config: EffectiveConfig,
        *,
        project_scenarios: Path | None = None,
        adapter_factory: AdapterFactory | None = None,
        dashboard_url: Callable[[str | None], str] | None = None,
    ) -> None:
        self.config = config
        self._runtime = RuntimeService(config)
        self._manager = RunManager()
        self._started = False
        self._project_scenarios = project_scenarios
        self._agent_catalog = create_agent_profile_catalog(config)
        self._catalog = create_scenario_catalog(
            config,
            project_dir=project_scenarios,
            workspace_root=(
                project_scenarios.parent if project_scenarios is not None else None
            ),
        )
        self._adapter_factory = adapter_factory or self._default_adapter
        self._dashboard_url = dashboard_url
        self._web_server: LocalWebServer | None = None
        self._background_tasks: anyio.abc.TaskGroup | None = None
        self._web_start_lock = anyio.Lock()

    def _default_adapter(self) -> AgentAdapter:
        return create_gigacode_adapter(self.config)

    async def __aenter__(self) -> McpToolService:
        if not self._started:
            background_tasks = anyio.create_task_group()
            await background_tasks.__aenter__()
            try:
                await self._manager.__aenter__()
            except BaseException:
                await background_tasks.__aexit__(None, None, None)
                raise
            self._background_tasks = background_tasks
            self._started = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._started:
            if self._web_server is not None:
                await self._web_server.stop()
                self._web_server = None
            await self._manager.__aexit__(exc_type, exc_value, traceback)
            background_tasks = self._background_tasks
            self._background_tasks = None
            if background_tasks is not None:
                await background_tasks.__aexit__(exc_type, exc_value, traceback)
            self._started = False

    def _require_started(self) -> None:
        if not self._started:
            raise AgentRuntimeError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "MCP runtime lifecycle has not started",
            )

    def _inline_scenario(self, text: str) -> LoadedScenario:
        if len(text.encode("utf-8")) > 2 * 1024 * 1024:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                "Inline scenario exceeds 2 MiB",
            )
        digest = sha256_digest(text).split(":", 1)[1]
        path = self.config.runtime.data_dir / "inline-scenarios" / f"{digest}.yaml"
        if not path.exists():
            atomic_write_text(path, text)
        return load_scenario_file(path, agent_catalog=self._agent_catalog)

    async def _ensure_dashboard(self, run_id: str | None) -> str:
        if self._dashboard_url is not None:
            return self._dashboard_url(run_id)
        if not self.config.web.enabled:
            raise AgentRuntimeError(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                "Local dashboard is disabled in runtime configuration",
            )
        async with self._web_start_lock:
            if self._web_server is None:
                from .web.server import LocalWebServer

                background_tasks = self._background_tasks
                if background_tasks is None:
                    raise AgentRuntimeError(
                        ErrorCode.INVALID_STATE_TRANSITION,
                        "MCP runtime lifecycle has not started",
                    )
                web_server = LocalWebServer(
                    self,
                    host=self.config.web.host,
                    port=self.config.web.port,
                )
                await web_server.start(task_group=background_tasks)
                self._web_server = web_server
        assert self._web_server is not None
        return self._web_server.url(run_id)

    def _scenario(
        self,
        *,
        scenario_name: str | None,
        inline_scenario: str | None,
    ) -> LoadedScenario:
        if bool(scenario_name) == bool(inline_scenario):
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                "Provide exactly one of scenario_name or inline_scenario_yaml",
            )
        if inline_scenario is not None:
            return self._inline_scenario(inline_scenario)
        assert scenario_name is not None
        return self._catalog.load(scenario_name)

    @staticmethod
    def _workspace(value: str) -> Path:
        path = Path(value).expanduser().resolve(strict=False)
        if not path.is_dir():
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                f"Workspace directory does not exist: {path}",
                details={"workspace": str(path)},
            )
        return path

    async def list_scenarios(self) -> dict[str, object]:
        def operation() -> dict[str, object]:
            scenarios = []
            entries = sorted(
                self._catalog.discover().values(),
                key=lambda entry: (
                    {"project": 0, "user": 1, "builtin": 2}.get(
                        entry.source.level,
                        3,
                    ),
                    entry.name,
                ),
            )
            for entry in entries:
                metadata = cast(Mapping[str, Any], entry.scenario.document["metadata"])
                scenarios.append(
                    {
                        "name": entry.name,
                        "title": entry.title,
                        "description": metadata.get("description"),
                        "source_level": entry.source.level,
                    }
                )
            return {"scenarios": scenarios}

        return await public_result(operation)

    @staticmethod
    def _agent_profile_document(
        profile: AgentProfile,
        *,
        include_prompt: bool,
    ) -> dict[str, object]:
        document: dict[str, object] = {
            "name": profile.name,
            "agent_ref": profile.reference,
            "description": profile.description,
            "source_path": str(profile.source_path),
            "model": profile.model,
            "approval_mode": profile.approval_mode,
            "tools": list(profile.tools),
            "disallowed_tools": list(profile.disallowed_tools),
            "color": profile.color,
            "scenario_model_required": True,
            "scenario_permissions_required": True,
        }
        if include_prompt:
            document["system_prompt"] = profile.system_prompt
        return document

    async def list_agent_profiles(self) -> dict[str, object]:
        def operation() -> dict[str, object]:
            profiles = [
                self._agent_profile_document(profile, include_prompt=False)
                for profile in sorted(
                    self._agent_catalog.discover().values(),
                    key=lambda item: item.name,
                )
            ]
            return {
                "catalog_root": str(self._agent_catalog.root),
                "agents": profiles,
            }

        return await public_result(operation)

    async def describe_agent_profile(self, agent_name: str) -> dict[str, object]:
        return await public_result(
            lambda: self._agent_profile_document(
                self._agent_catalog.load(agent_name),
                include_prompt=True,
            )
        )

    async def describe_scenario(self, scenario_name: str) -> dict[str, object]:
        def operation() -> dict[str, object]:
            scenario = self._catalog.load(scenario_name)
            steps = cast(Mapping[str, object], scenario.document["steps"])
            return {
                "name": scenario.name,
                "schema_version": str(scenario.document["schema_version"]),
                "kind": str(scenario.document["kind"]),
                "source_level": scenario.source.level,
                "metadata": dict(
                    cast(Mapping[str, object], scenario.document["metadata"])
                ),
                "inputs": dict(
                    cast(Mapping[str, object], scenario.document.get("inputs", {}))
                ),
                "agents": dict(
                    cast(Mapping[str, object], scenario.document["agents"])
                ),
                "step_names": list(steps.keys()),
                "steps": dict(steps),
                "max_parallel_agents": scenario.document.get(
                    "max_parallel_agents",
                ),
                "result": dict(
                    cast(Mapping[str, object], scenario.document["result"])
                ),
                "resolved_agent_refs": [
                    self._agent_profile_document(profile, include_prompt=False)
                    for profile in sorted(
                        scenario.agent_profiles.values(),
                        key=lambda item: item.name,
                    )
                ],
            }

        return await public_result(operation)

    async def validate_scenario(
        self,
        scenario_name: str | None = None,
        inline_scenario: str | None = None,
    ) -> dict[str, object]:
        def operation() -> dict[str, object]:
            scenario = self._scenario(
                scenario_name=scenario_name,
                inline_scenario=inline_scenario,
            )
            return {
                "valid": True,
                "name": scenario.name,
                "resource_count": len(scenario.resources),
                "agent_refs": sorted(scenario.agent_profiles),
            }

        return await public_result(operation)

    async def plan_scenario(
        self,
        workspace: str,
        scenario_name: str | None = None,
        inline_scenario: str | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        def operation() -> dict[str, object]:
            scenario = self._scenario(
                scenario_name=scenario_name,
                inline_scenario=inline_scenario,
            )
            plan = compile_plan(
                scenario,
                self.config,
                inputs=inputs or {},
                workspace=self._workspace(workspace),
            )
            return execution_plan_to_document(plan)

        return await public_result(operation)

    async def diagnose_runtime(
        self,
        subprocess_smoke: bool = False,
    ) -> dict[str, object]:
        async def operation() -> dict[str, object]:
            return await diagnose_runtime(
                self.config,
                self._adapter_factory,
                subprocess_smoke=subprocess_smoke,
            )

        return await public_result(operation)

    async def start_run(
        self,
        workspace: str,
        scenario_name: str | None = None,
        inline_scenario: str | None = None,
        inputs: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        async def operation() -> dict[str, object]:
            self._require_started()
            scenario = self._scenario(
                scenario_name=scenario_name,
                inline_scenario=inline_scenario,
            )
            prepared = self._runtime.start_run(
                scenario,
                inputs=inputs or {},
                workspace=self._workspace(workspace),
                idempotency_key=idempotency_key,
            )
            dashboard_url = (
                await self._ensure_dashboard(prepared.run_id)
                if self.config.web.enabled
                else None
            )
            if (
                prepared.state.status is RunStatus.PLANNED
                or self._manager.has_active(prepared.run_id)
            ):
                self._manager.submit(
                    prepared,
                    DagScheduler(prepared.config, self._adapter_factory()),
                )
            return {
                "run_id": prepared.run_id,
                "status": prepared.state.status.value,
                "plan_hash": prepared.plan.plan_hash,
                "dashboard_url": dashboard_url,
            }

        return await public_result(operation)

    async def get_run_status(self, run_id: str) -> dict[str, object]:
        return await public_result(
            lambda: run_state_to_document(
                StateStore(self.config.paths.runs).read(run_id)
            )
        )

    async def get_run_events(
        self,
        run_id: str,
        after: int = 0,
        limit: int = 100,
    ) -> dict[str, object]:
        def operation() -> dict[str, object]:
            states = StateStore(self.config.paths.runs)
            states.read(run_id)
            run_dir = states.run_dir(run_id)
            page = EventLog(run_dir, run_id=run_id).read(after=after, limit=limit)
            return {
                "events": [event_to_document(event) for event in page.events],
                "next_cursor": page.next_cursor,
                "has_more": page.has_more,
            }

        return await public_result(operation)

    async def get_run_result(self, run_id: str) -> dict[str, object]:
        return await public_result(lambda: self._runtime.get_result(run_id))

    async def get_run_artifacts(
        self,
        run_id: str,
        after: int = 0,
        limit: int = 100,
    ) -> dict[str, object]:
        def operation() -> dict[str, object]:
            prepared = self._runtime.open_run(run_id, recover_running=False)
            return prepared.artifacts.list(after=after, limit=limit)

        return await public_result(operation)

    async def provide_input(
        self,
        run_id: str,
        gate_id: str,
        value: Any,
    ) -> dict[str, object]:
        return await public_result(
            lambda: InputGateStore(
                self.config.paths.runs,
                run_id,
            ).provide(gate_id, value)
        )

    async def approve_run(
        self,
        run_id: str,
        plan_hash: str,
        gate: str = "full_access",
    ) -> dict[str, object]:
        def operation() -> dict[str, object]:
            prepared = self._runtime.open_run(run_id, recover_running=False)
            if prepared.plan.plan_hash != plan_hash:
                raise AgentRuntimeError(
                    ErrorCode.PERMISSION_DENIED,
                    "Approval hash does not match the immutable run plan",
                    details={"run_id": run_id, "plan_hash": plan_hash},
                )
            record = ApprovalStore(prepared.run_dir).approve(
                run_id,
                plan_hash,
                gate,
            )
            return {
                "run_id": record.run_id,
                "plan_hash": record.plan_hash,
                "gate": record.gate,
                "approved_at": record.approved_at,
            }

        return await public_result(operation)

    async def pause_run(self, run_id: str) -> dict[str, object]:
        def operation() -> dict[str, object]:
            self._manager.control(run_id).pause()
            return {"run_id": run_id, "pause_requested": True}

        return await public_result(operation)

    async def resume_run(self, run_id: str) -> dict[str, object]:
        def operation() -> dict[str, object]:
            self._require_started()
            prepared = self._runtime.prepare_resume(run_id)
            self._manager.submit(
                prepared,
                DagScheduler(prepared.config, self._adapter_factory()),
            )
            return {
                "run_id": run_id,
                "status": prepared.state.status.value,
                "plan_hash": prepared.plan.plan_hash,
            }

        return await public_result(operation)

    async def cancel_run(self, run_id: str) -> dict[str, object]:
        def operation() -> dict[str, object]:
            try:
                self._manager.control(run_id).cancel()
            except AgentRuntimeError as error:
                if error.code is not ErrorCode.RUN_NOT_FOUND:
                    raise
                states = StateStore(self.config.paths.runs)
                state = states.read(run_id)
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
                    ) from None
                states.finish(
                    run_id,
                    RunStatus.CANCELLED,
                    error={"code": "CANCELLED", "message": "Run was cancelled"},
                )
            return {"run_id": run_id, "cancel_requested": True}

        return await public_result(operation)

    async def open_dashboard(self, run_id: str | None = None) -> dict[str, object]:
        async def operation() -> dict[str, object]:
            self._require_started()
            return {"url": await self._ensure_dashboard(run_id)}

        return await public_result(operation)
