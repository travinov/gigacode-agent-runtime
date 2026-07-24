"""Durable review/repair loop execution over an inner agent DAG."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

import anyio

from .cancellation import ExecutionControl
from .conditions import evaluate_condition
from .domain import (
    ExecutionPlan,
    LoopStepDefinition,
    OnLimit,
    PermissionMode,
    StepState,
    StepStatus,
)
from .errors import AgentRuntimeError, ErrorCode
from .event_log import EventLog
from .hashing import sha256_digest
from .interpolation import interpolate
from .state_store import StateStore
from .step_runner import LoopContext, StepOutcome, StepRunner


class LoopController:
    def __init__(
        self,
        *,
        plan: ExecutionPlan,
        run_id: str,
        states: StateStore,
        events: EventLog,
        runner: StepRunner,
        general_limiter: anyio.CapacityLimiter,
        full_access_limiter: anyio.CapacityLimiter,
    ) -> None:
        self._plan = plan
        self._run_id = run_id
        self._states = states
        self._events = events
        self._runner = runner
        self._general_limiter = general_limiter
        self._full_access_limiter = full_access_limiter

    def _saved_iterations(
        self,
        loop: LoopStepDefinition,
    ) -> dict[int, dict[str, StepState]]:
        body_names = {step.name for step in loop.body}
        pattern = re.compile(r"^(.+)@iteration-([1-9][0-9]*)$")
        iterations: dict[int, dict[str, StepState]] = {}
        for instance_id, state in self._states.read(self._run_id).steps.items():
            matched = pattern.fullmatch(instance_id)
            if matched is None or matched.group(1) not in body_names:
                continue
            iteration = int(matched.group(2))
            iterations.setdefault(iteration, {})[matched.group(1)] = state
        return iterations

    @staticmethod
    def _outputs(states: Mapping[str, StepState]) -> dict[str, Mapping[str, object]]:
        return {
            name: state.output
            for name, state in states.items()
            if state.status is StepStatus.COMPLETED and state.output is not None
        }

    def _context(
        self,
        iteration: int,
        current: Mapping[str, Mapping[str, object]],
        previous: Mapping[str, Mapping[str, object]],
    ) -> LoopContext:
        return LoopContext(
            iteration=iteration,
            current=current,
            previous=previous,
        )

    def _condition(
        self,
        condition: Mapping[str, object],
        context: LoopContext,
    ) -> bool:
        return evaluate_condition(
            condition,
            lambda reference: self._runner.resolve_reference(
                reference,
                loop_context=context,
            ),
        )

    def _loop_output(
        self,
        iteration: int,
        outputs: Mapping[str, Mapping[str, object]],
    ) -> dict[str, object]:
        return {
            "iteration": iteration,
            "steps": {
                name: dict(output)
                for name, output in sorted(outputs.items())
            },
        }

    def _complete(
        self,
        loop: LoopStepDefinition,
        *,
        iteration: int,
        outputs: Mapping[str, Mapping[str, object]],
        best_effort: bool = False,
    ) -> StepOutcome:
        output = self._loop_output(iteration, outputs)
        self._states.put_step(
            self._run_id,
            StepState(
                instance_id=loop.name,
                status=StepStatus.COMPLETED,
                attempt=1,
                iteration=iteration,
                output=output,
            ),
        )
        self._events.append(
            "loop.completed",
            {
                "step": loop.name,
                "iteration": iteration,
                "best_effort": best_effort,
            },
            step_instance_id=loop.name,
        )
        return StepOutcome(
            instance_id=loop.name,
            output=output,
            error=None,
            attempt=1,
            best_effort=best_effort,
        )

    def _limit(
        self,
        loop: LoopStepDefinition,
        *,
        reason: str,
        iteration: int,
        outputs: Mapping[str, Mapping[str, object]],
    ) -> StepOutcome:
        error_code = (
            ErrorCode.NO_PROGRESS if reason == "no_progress" else ErrorCode.LOOP_LIMIT
        )
        error = AgentRuntimeError(
            error_code,
            f"Loop {loop.name} stopped because of {reason}",
            details={
                "step": loop.name,
                "reason": reason,
                "iteration": iteration,
                "max_iterations": loop.max_iterations,
                "on_limit": loop.on_limit.value,
            },
        )
        self._events.append(
            "loop.limit_reached",
            error.to_dict(),
            step_instance_id=loop.name,
        )
        if loop.on_limit is OnLimit.BEST_EFFORT:
            return self._complete(
                loop,
                iteration=iteration,
                outputs=outputs,
                best_effort=True,
            )
        if loop.on_limit is OnLimit.PAUSE:
            self._states.put_step(
                self._run_id,
                StepState(
                    instance_id=loop.name,
                    status=StepStatus.BLOCKED,
                    attempt=1,
                    iteration=iteration,
                    output=self._loop_output(iteration, outputs),
                    error=error.to_dict(),
                ),
            )
            return StepOutcome(
                instance_id=loop.name,
                output=self._loop_output(iteration, outputs),
                error=None,
                attempt=1,
                paused=True,
            )
        self._states.put_step(
            self._run_id,
            StepState(
                instance_id=loop.name,
                status=StepStatus.FAILED,
                attempt=1,
                iteration=iteration,
                error=error.to_dict(),
            ),
        )
        return StepOutcome(loop.name, None, error, 1)

    def _fingerprint(
        self,
        no_progress: Mapping[str, object],
        context: LoopContext,
    ) -> str:
        references = no_progress["fingerprint"]
        if not isinstance(references, Sequence) or isinstance(references, (str, bytes)):
            raise AgentRuntimeError(
                ErrorCode.CONDITION_ERROR,
                "Loop no-progress fingerprint must be an array",
            )
        values = [
            interpolate(
                str(reference),
                lambda item: self._runner.resolve_reference(
                    item,
                    loop_context=context,
                ),
            )
            for reference in references
        ]
        return sha256_digest(values)

    async def _run_inner_step(
        self,
        step_name: str,
        loop: LoopStepDefinition,
        context: LoopContext,
        outcomes: dict[str, StepOutcome],
    ) -> None:
        step = next(item for item in loop.body if item.name == step_name)
        agent = self._plan.agents[step.agent]
        async with self._general_limiter:
            if agent.permissions is PermissionMode.FULL_ACCESS:
                async with self._full_access_limiter:
                    outcome = await self._runner.run(
                        step,
                        iteration=context.iteration,
                        loop_context=context,
                    )
            else:
                outcome = await self._runner.run(
                    step,
                    iteration=context.iteration,
                    loop_context=context,
                )
        outcomes[step_name] = outcome

    async def _execute(
        self,
        loop: LoopStepDefinition,
        control: ExecutionControl,
    ) -> StepOutcome:
        saved = self._saved_iterations(loop)
        iteration = max(saved, default=1)
        previous = self._outputs(saved.get(iteration - 1, {}))
        current_states = saved.get(iteration, {})
        current = self._outputs(current_states)
        previous_fingerprint: str | None = None
        unchanged = 0

        self._states.put_step(
            self._run_id,
            StepState(
                instance_id=loop.name,
                status=StepStatus.RUNNING,
                attempt=1,
                iteration=iteration,
            ),
        )
        self._events.append(
            "loop.started",
            {"step": loop.name, "iteration": iteration},
            step_instance_id=loop.name,
        )

        while iteration <= loop.max_iterations:
            if control.stop_requested:
                return StepOutcome(loop.name, None, None, 1, cancelled=True)
            context = self._context(iteration, current, previous)
            self._events.append(
                "loop.iteration_started",
                {"step": loop.name, "iteration": iteration},
                step_instance_id=loop.name,
            )

            for wave in loop.waves:
                pending: list[str] = []
                for name in wave:
                    existing = current_states.get(name)
                    if (
                        existing is not None
                        and existing.status is StepStatus.COMPLETED
                        and existing.output is not None
                    ):
                        current[name] = existing.output
                        continue
                    step = next(item for item in loop.body if item.name == name)
                    context = self._context(iteration, current, previous)
                    if step.condition is not None and not self._condition(
                        step.condition,
                        context,
                    ):
                        self._runner.mark_skipped(step, iteration=iteration)
                        current_states[name] = self._states.read(self._run_id).steps[
                            f"{name}@iteration-{iteration}"
                        ]
                        continue
                    self._runner.mark_ready(step, iteration=iteration)
                    pending.append(name)

                outcomes: dict[str, StepOutcome] = {}
                async with anyio.create_task_group() as task_group:
                    for name in pending:
                        task_group.start_soon(
                            self._run_inner_step,
                            name,
                            loop,
                            self._context(iteration, current, previous),
                            outcomes,
                        )
                for name in pending:
                    outcome = outcomes[name]
                    if outcome.cancelled:
                        return StepOutcome(loop.name, None, None, 1, cancelled=True)
                    if outcome.error is not None:
                        self._states.put_step(
                            self._run_id,
                            StepState(
                                instance_id=loop.name,
                                status=StepStatus.FAILED,
                                attempt=1,
                                iteration=iteration,
                                error=outcome.error.to_dict(),
                            ),
                        )
                        return StepOutcome(loop.name, None, outcome.error, 1)
                    assert outcome.output is not None
                    current[name] = outcome.output
                    current_states[name] = self._states.read(self._run_id).steps[
                        f"{name}@iteration-{iteration}"
                    ]

                context = self._context(iteration, current, previous)
                condition_met = self._condition(loop.until, context)
                self._events.append(
                    "loop.condition_evaluated",
                    {
                        "step": loop.name,
                        "iteration": iteration,
                        "result": condition_met,
                    },
                    step_instance_id=loop.name,
                )
                if condition_met:
                    return self._complete(
                        loop,
                        iteration=iteration,
                        outputs=current,
                    )

            if loop.no_progress is not None:
                context = self._context(iteration, current, previous)
                fingerprint = self._fingerprint(loop.no_progress, context)
                unchanged = unchanged + 1 if fingerprint == previous_fingerprint else 0
                previous_fingerprint = fingerprint
                threshold_raw = loop.no_progress["max_unchanged_iterations"]
                if not isinstance(threshold_raw, int):
                    raise AgentRuntimeError(
                        ErrorCode.CONDITION_ERROR,
                        "max_unchanged_iterations must be an integer",
                    )
                threshold = threshold_raw
                if unchanged >= threshold:
                    self._events.append(
                        "loop.no_progress",
                        {
                            "step": loop.name,
                            "iteration": iteration,
                            "unchanged_iterations": unchanged,
                        },
                        step_instance_id=loop.name,
                    )
                    return self._limit(
                        loop,
                        reason="no_progress",
                        iteration=iteration,
                        outputs=current,
                    )

            previous = dict(current)
            iteration += 1
            current = {}
            current_states = saved.get(iteration, {})

        return self._limit(
            loop,
            reason="max_iterations",
            iteration=loop.max_iterations,
            outputs=previous,
        )

    async def run(
        self,
        loop: LoopStepDefinition,
        *,
        control: ExecutionControl,
    ) -> StepOutcome:
        try:
            with anyio.fail_after(loop.timeout_seconds):
                return await self._execute(loop, control)
        except TimeoutError:
            loop_state = self._states.read(self._run_id).steps.get(loop.name)
            iteration = (
                loop_state.iteration
                if loop_state is not None and loop_state.iteration is not None
                else 1
            )
            return self._limit(
                loop,
                reason="timeout",
                iteration=iteration,
                outputs={},
            )
