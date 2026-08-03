"""Application service shared by the CLI, MCP server, and Web UI."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .artifacts import ArtifactStore
from .config import EffectiveConfig
from .domain import ExecutionPlan, RunStatus
from .errors import AgentRuntimeError, ErrorCode
from .event_log import EventLog
from .hashing import sha256_digest
from .idempotency import IdempotencyStore
from .plan_compiler import compile_plan
from .resume import open_prepared_run
from .run_factory import PreparedRun, create_run
from .scenario_loader import LoadedScenario
from .state_store import StateStore


class RuntimeService:
    def __init__(self, config: EffectiveConfig) -> None:
        self.config = config
        self._states = StateStore(config.paths.runs)
        self._idempotency = IdempotencyStore(config.runtime.data_dir)

    def _prepared_existing(self, run_id: str, plan: ExecutionPlan) -> PreparedRun:
        state = self._states.read(run_id)
        run_dir = self._states.run_dir(run_id)
        return PreparedRun(
            run_id=run_id,
            run_dir=run_dir,
            config=self.config,
            plan=plan,
            state=state,
            events=EventLog(run_dir, run_id=run_id),
            artifacts=ArtifactStore(
                run_dir,
                max_bytes=self.config.runtime.max_stdout_bytes_per_step,
            ),
        )

    def start_run(
        self,
        scenario: LoadedScenario,
        *,
        inputs: Mapping[str, object],
        workspace: Path,
        idempotency_key: str | None = None,
    ) -> PreparedRun:
        plan = compile_plan(
            scenario,
            self.config,
            inputs=inputs,
            workspace=workspace,
        )

        def create() -> str:
            return create_run(
                self._states,
                scenario=scenario,
                config=self.config,
                plan=plan,
            ).run_id

        if idempotency_key is None:
            run_id = create()
        else:
            signature = sha256_digest(
                {
                    "operation": "start_run",
                    "plan_hash": plan.plan_hash,
                    "inputs_hash": plan.inputs_hash,
                }
            )
            run_id = self._idempotency.get_or_create(
                idempotency_key,
                signature,
                create,
            )
        return self._prepared_existing(run_id, plan)

    def get_result(self, run_id: str) -> dict[str, object]:
        state = self._states.read(run_id)
        return {
            "run_id": state.run_id,
            "status": state.status.value,
            "result": dict(state.result) if state.result is not None else None,
        }

    def open_run(
        self,
        run_id: str,
        *,
        recover_running: bool = True,
    ) -> PreparedRun:
        return open_prepared_run(
            self.config,
            run_id,
            recover_running=recover_running,
        )

    def prepare_resume(self, run_id: str) -> PreparedRun:
        prepared = self.open_run(run_id)
        if prepared.state.status not in {
            RunStatus.INTERRUPTED,
            RunStatus.PAUSED,
            RunStatus.WAITING_FOR_APPROVAL,
        }:
            raise AgentRuntimeError(
                ErrorCode.INVALID_STATE_TRANSITION,
                f"Run cannot be resumed from {prepared.state.status.value}",
                details={
                    "run_id": run_id,
                    "status": prepared.state.status.value,
                },
            )
        return prepared
