"""MCP-facing application use cases with bounded, path-safe results."""

from __future__ import annotations

import importlib.metadata
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from .adapter_factory import create_gigacode_adapter
from .approval_store import ApprovalStore
from .config import EffectiveConfig
from .domain import RunStatus
from .errors import AgentRuntimeError, ErrorCode
from .event_log import EventLog, event_to_document
from .hashing import sha256_digest
from .input_gates import InputGateStore
from .mcp_errors import public_result
from .plan_compiler import compile_plan, execution_plan_to_document
from .run_manager import RunManager
from .runtime_service import RuntimeService
from .scenario_loader import LoadedScenario, ScenarioCatalog, load_scenario_file
from .scheduler import DagScheduler
from .serialization import atomic_write_text
from .state_store import StateStore, run_state_to_document
from .step_runner import AgentAdapter

AdapterFactory = Callable[[], AgentAdapter]


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
        self._catalog = ScenarioCatalog(
            user_dir=config.paths.user_scenarios,
            project_dir=project_scenarios,
            workspace_root=(
                project_scenarios.parent if project_scenarios is not None else None
            ),
        )
        self._adapter_factory = adapter_factory or self._default_adapter
        self._dashboard_url = dashboard_url

    def _default_adapter(self) -> AgentAdapter:
        return create_gigacode_adapter(self.config)

    async def __aenter__(self) -> McpToolService:
        if not self._started:
            await self._manager.__aenter__()
            self._started = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        if self._started:
            await self._manager.__aexit__(exc_type, exc_value, traceback)
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
        return load_scenario_file(path)

    def _scenario(
        self,
        *,
        scenario_name: str | None,
        inline_scenario: str | None,
    ) -> LoadedScenario:
        if bool(scenario_name) == bool(inline_scenario):
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                "Provide exactly one of scenario_name or inline_scenario",
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
            for entry in self._catalog.discover().values():
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

    async def describe_scenario(self, scenario_name: str) -> dict[str, object]:
        def operation() -> dict[str, object]:
            scenario = self._catalog.load(scenario_name)
            return {
                "name": scenario.name,
                "metadata": dict(
                    cast(Mapping[str, object], scenario.document["metadata"])
                ),
                "inputs": dict(
                    cast(Mapping[str, object], scenario.document.get("inputs", {}))
                ),
                "agents": dict(
                    cast(Mapping[str, object], scenario.document["agents"])
                ),
                "steps": list(
                    cast(Mapping[str, object], scenario.document["steps"]).keys()
                ),
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

    async def diagnose_runtime(self) -> dict[str, object]:
        async def operation() -> dict[str, object]:
            adapter = self._adapter_factory()
            capabilities = await adapter.detect_capabilities()
            return {
                "runtime_version": importlib.metadata.version(
                    "gigacode-agent-runtime"
                ),
                "mcp_sdk_version": importlib.metadata.version("mcp"),
                "python": sys.version.split()[0],
                "capabilities": capabilities.to_snapshot(),
                "data_dir_writable": os.access(
                    self.config.runtime.data_dir.parent,
                    os.W_OK,
                ),
            }

        return await public_result(operation)

    async def start_run(
        self,
        workspace: str,
        scenario_name: str | None = None,
        inline_scenario: str | None = None,
        inputs: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        def operation() -> dict[str, object]:
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
                "dashboard_url": (
                    self._dashboard_url(prepared.run_id)
                    if self._dashboard_url is not None
                    else None
                ),
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
        def operation() -> dict[str, object]:
            if self._dashboard_url is None:
                raise AgentRuntimeError(
                    ErrorCode.CAPABILITY_UNAVAILABLE,
                    "Local dashboard is not started",
                )
            return {"url": self._dashboard_url(run_id)}

        return await public_result(operation)
