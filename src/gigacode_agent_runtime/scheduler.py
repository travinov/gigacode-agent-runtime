"""Deterministic AnyIO DAG scheduler for top-level agent steps."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import anyio

from .adapters.capabilities import GigaCodeCapabilities
from .approval_store import ApprovalStore
from .cancellation import ExecutionControl
from .conditions import evaluate_condition
from .config import EffectiveConfig
from .domain import (
    AgentStepDefinition,
    LoopStepDefinition,
    PermissionMode,
    RunState,
    RunStatus,
    StepState,
    StepStatus,
)
from .errors import AgentRuntimeError, ErrorCode
from .locking import FileLock
from .loop_controller import LoopController
from .permissions import PermissionController
from .run_factory import PreparedRun
from .serialization import atomic_write_json
from .state_store import StateStore
from .step_runner import AgentAdapter, StepOutcome, StepRunner


@dataclass(frozen=True, slots=True)
class SchedulerResult:
    state: RunState
    capabilities: GigaCodeCapabilities


@dataclass(slots=True)
class _WaveState:
    outcomes: dict[str, StepOutcome] = field(default_factory=dict)
    failure_name: str | None = None


class DagScheduler:
    def __init__(
        self,
        config: EffectiveConfig,
        adapter: AgentAdapter,
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._states = StateStore(config.paths.runs)

    @staticmethod
    def _resolve_result(
        reference: str,
        outputs: Mapping[str, Mapping[str, object]],
    ) -> Mapping[str, object]:
        prefix = "${steps."
        suffix = ".output}"
        if not reference.startswith(prefix) or not reference.endswith(suffix):
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Unsupported result reference: {reference}",
                details={"reference": reference},
            )
        name = reference[len(prefix) : -len(suffix)]
        output = outputs.get(name)
        if output is None:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Result step did not produce output: {name}",
                details={"step": name},
            )
        return output

    def _block_pending(
        self,
        prepared: PreparedRun,
        *,
        excluded: set[str],
        failed_step: str,
    ) -> None:
        for step in prepared.plan.steps:
            if step.name in excluded:
                continue
            existing = self._states.read(prepared.run_id).steps.get(step.name)
            if existing is not None and existing.status in {
                StepStatus.COMPLETED,
                StepStatus.FAILED,
                StepStatus.CANCELLED,
            }:
                continue
            self._states.put_step(
                prepared.run_id,
                StepState(
                    instance_id=step.name,
                    status=StepStatus.BLOCKED,
                    error={
                        "code": "UPSTREAM_FAILED",
                        "failed_step": failed_step,
                    },
                ),
            )
            prepared.events.append(
                "step.blocked",
                {"step": step.name, "failed_step": failed_step},
                step_instance_id=step.name,
            )

    def _finish_stopped(
        self,
        prepared: PreparedRun,
        control: ExecutionControl,
        *,
        wave: int,
    ) -> RunState:
        if control.interrupt_requested:
            current = self._states.read(prepared.run_id)
            for instance_id, step in current.steps.items():
                if step.status is StepStatus.CANCELLED:
                    self._states.put_step(
                        prepared.run_id,
                        StepState(
                            instance_id=instance_id,
                            status=StepStatus.INTERRUPTED,
                            attempt=step.attempt,
                            iteration=step.iteration,
                            output=step.output,
                            error=step.error,
                        ),
                    )
            state = self._states.finish(
                prepared.run_id,
                RunStatus.INTERRUPTED,
                error={
                    "code": "INTERRUPTED",
                    "message": "Runtime stopped before the run completed",
                },
            )
            prepared.events.append("run.interrupted", {"wave": wave})
            return state
        state = self._states.finish(
            prepared.run_id,
            RunStatus.CANCELLED,
            error={"code": "CANCELLED", "message": "Run was cancelled"},
        )
        prepared.events.append("run.cancelled", {"wave": wave})
        return state

    async def run(
        self,
        prepared: PreparedRun,
        *,
        control: ExecutionControl | None = None,
    ) -> SchedulerResult:
        active_control = control or ExecutionControl()
        writer_lock = FileLock(prepared.run_dir / "writer.lock")
        writer_lock.acquire()
        try:
            current = self._states.read(prepared.run_id)
            resumable = {
                RunStatus.PLANNED,
                RunStatus.PAUSED,
                RunStatus.INTERRUPTED,
                RunStatus.WAITING_FOR_APPROVAL,
            }
            if current.status not in resumable:
                raise AgentRuntimeError(
                    ErrorCode.INVALID_STATE_TRANSITION,
                    f"Run cannot be executed from {current.status.value}",
                    details={"run_id": prepared.run_id, "status": current.status.value},
                )

            capabilities = await self._adapter.detect_capabilities()
            atomic_write_json(
                prepared.run_dir / "capabilities.snapshot.json",
                capabilities.to_snapshot(),
            )
            controller = PermissionController(
                prepared.config,
                ApprovalStore(prepared.run_dir),
            )
            try:
                decision = controller.authorize(
                    prepared.plan,
                    prepared.run_id,
                    capabilities,
                )
            except AgentRuntimeError as caught:
                if caught.code is ErrorCode.APPROVAL_REQUIRED:
                    state = (
                        current
                        if current.status is RunStatus.WAITING_FOR_APPROVAL
                        else self._states.transition(
                            prepared.run_id,
                            RunStatus.WAITING_FOR_APPROVAL,
                        )
                    )
                    prepared.events.append(
                        "run.approval_required",
                        caught.to_dict(),
                    )
                    return SchedulerResult(state=state, capabilities=capabilities)
                raise

            state = self._states.transition(prepared.run_id, RunStatus.RUNNING)
            if current.status is RunStatus.PLANNED:
                prepared.events.append(
                    "run.started",
                    {
                        "plan_hash": prepared.plan.plan_hash,
                        "max_parallel_agents": prepared.plan.max_parallel_agents,
                    },
                )
            else:
                prepared.events.append(
                    "run.resumed",
                    {
                        "previous_status": current.status.value,
                        "plan_hash": prepared.plan.plan_hash,
                    },
                )
            runner = StepRunner(
                plan=prepared.plan,
                run_id=prepared.run_id,
                adapter=self._adapter,
                capabilities=capabilities,
                states=self._states,
                events=prepared.events,
                artifacts=prepared.artifacts,
            )
            general_limiter = anyio.CapacityLimiter(
                prepared.plan.max_parallel_agents
            )
            full_access_limiter = anyio.CapacityLimiter(
                decision.max_parallel_full_access_agents
            )
            loop_controller = LoopController(
                plan=prepared.plan,
                run_id=prepared.run_id,
                states=self._states,
                events=prepared.events,
                runner=runner,
                general_limiter=general_limiter,
                full_access_limiter=full_access_limiter,
            )
            steps_by_name = {step.name: step for step in prepared.plan.steps}
            resumed_state = self._states.read(prepared.run_id)
            outputs: dict[str, Mapping[str, object]] = {
                name: step.output
                for name, step in resumed_state.steps.items()
                if name in steps_by_name
                and step.status is StepStatus.COMPLETED
                and step.output is not None
            }
            completed_names: set[str] = set(outputs)
            failure: tuple[str, AgentRuntimeError] | None = None
            best_effort = False

            for wave_index, wave in enumerate(prepared.plan.waves, start=1):
                if active_control.stop_requested:
                    state = self._finish_stopped(
                        prepared,
                        active_control,
                        wave=wave_index,
                    )
                    return SchedulerResult(state=state, capabilities=capabilities)
                if active_control.pause_requested:
                    state = self._states.transition(prepared.run_id, RunStatus.PAUSED)
                    prepared.events.append("run.paused", {"before_wave": wave_index})
                    return SchedulerResult(state=state, capabilities=capabilities)

                pending_wave: list[str] = []
                for name in wave:
                    step = steps_by_name[name]
                    existing = self._states.read(prepared.run_id).steps.get(name)
                    if (
                        existing is not None
                        and existing.status is StepStatus.COMPLETED
                        and existing.output is not None
                    ):
                        outputs[name] = existing.output
                        completed_names.add(name)
                        continue
                    if (
                        isinstance(step, AgentStepDefinition)
                        and step.condition is not None
                        and not evaluate_condition(
                            step.condition,
                            runner.resolve_reference,
                        )
                    ):
                        runner.mark_skipped(step)
                        continue
                    if isinstance(step, AgentStepDefinition):
                        runner.mark_ready(step)
                    else:
                        self._states.put_step(
                            prepared.run_id,
                            StepState(
                                instance_id=step.name,
                                status=StepStatus.READY,
                            ),
                        )
                    pending_wave.append(name)

                if not pending_wave:
                    continue

                wave_state = _WaveState()
                external_cancelled = False

                async with anyio.create_task_group() as task_group:
                    async def monitor_cancel() -> None:
                        nonlocal external_cancelled
                        await active_control.wait_stopped()
                        external_cancelled = True
                        task_group.cancel_scope.cancel()

                    async def execute(
                        name: str,
                        current_wave: _WaveState,
                        cancel_scope: anyio.CancelScope,
                    ) -> None:
                        raw_step = steps_by_name[name]
                        if isinstance(raw_step, LoopStepDefinition):
                            outcome = await loop_controller.run(
                                raw_step,
                                control=active_control,
                            )
                        else:
                            agent = prepared.plan.agents[raw_step.agent]
                            async with general_limiter:
                                if agent.permissions is PermissionMode.FULL_ACCESS:
                                    async with full_access_limiter:
                                        outcome = await runner.run(raw_step)
                                else:
                                    outcome = await runner.run(raw_step)
                        current_wave.outcomes[name] = outcome
                        if (
                            outcome.error is not None
                            and current_wave.failure_name is None
                        ):
                            current_wave.failure_name = name
                            cancel_scope.cancel()

                    task_group.start_soon(monitor_cancel)
                    for name in pending_wave:
                        task_group.start_soon(
                            execute,
                            name,
                            wave_state,
                            task_group.cancel_scope,
                        )

                    while len(wave_state.outcomes) < len(pending_wave):
                        if wave_state.failure_name is not None or external_cancelled:
                            break
                        await anyio.sleep(0.005)
                    if len(wave_state.outcomes) == len(pending_wave):
                        task_group.cancel_scope.cancel()

                if external_cancelled:
                    state = self._finish_stopped(
                        prepared,
                        active_control,
                        wave=wave_index,
                    )
                    return SchedulerResult(state=state, capabilities=capabilities)

                pause_from_loop = False
                for name in pending_wave:
                    outcome = wave_state.outcomes.get(name)
                    if outcome is not None and outcome.succeeded:
                        assert outcome.output is not None
                        outputs[name] = outcome.output
                        completed_names.add(name)
                        best_effort = best_effort or outcome.best_effort
                    elif outcome is not None and outcome.paused:
                        pause_from_loop = True
                    elif outcome is not None and outcome.error is not None:
                        failure = (name, outcome.error)
                        break

                prepared.events.append(
                    "run.heartbeat",
                    {
                        "wave": wave_index,
                        "completed_steps": sorted(completed_names),
                    },
                )
                if failure is not None:
                    failed_name, failed_error = failure
                    self._block_pending(
                        prepared,
                        excluded=completed_names | {failed_name},
                        failed_step=failed_name,
                    )
                    state = self._states.finish(
                        prepared.run_id,
                        RunStatus.FAILED,
                        error=failed_error.to_dict(),
                    )
                    prepared.events.append(
                        "run.failed",
                        {
                            "failed_step": failed_name,
                            "error": failed_error.to_dict(),
                        },
                    )
                    return SchedulerResult(state=state, capabilities=capabilities)

                if active_control.pause_requested or pause_from_loop:
                    state = self._states.transition(prepared.run_id, RunStatus.PAUSED)
                    prepared.events.append(
                        "run.paused",
                        {
                            "after_wave": wave_index,
                            "reason": (
                                "loop_limit"
                                if pause_from_loop
                                else "user_requested"
                            ),
                        },
                    )
                    return SchedulerResult(state=state, capabilities=capabilities)

            result = self._resolve_result(prepared.plan.result_reference, outputs)
            state = self._states.finish(
                prepared.run_id,
                (
                    RunStatus.COMPLETED_BEST_EFFORT
                    if best_effort
                    else RunStatus.COMPLETED
                ),
                result=MappingProxyType(dict(result)),
            )
            prepared.events.append(
                "run.completed",
                {"result_step": prepared.plan.result_reference},
            )
            return SchedulerResult(state=state, capabilities=capabilities)
        finally:
            writer_lock.release()
