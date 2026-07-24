"""Execute one agent step with interpolation, retry, and durable events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import anyio

from .adapters.capabilities import GigaCodeCapabilities
from .adapters.gigacode_qwen import (
    AgentExecutionResult,
    AgentRequest,
)
from .artifacts import ArtifactStore
from .domain import AgentStepDefinition, ExecutionPlan, StepState, StepStatus
from .errors import AgentRuntimeError, ErrorCode
from .event_log import EventLog
from .hashing import canonical_json
from .interpolation import interpolate
from .retry import classify_failure, retry_delay, should_retry
from .state_store import StateStore


class AgentAdapter(Protocol):
    async def detect_capabilities(self) -> GigaCodeCapabilities: ...

    async def run_agent(
        self,
        request: AgentRequest,
        *,
        timeout_seconds: float,
        capabilities: GigaCodeCapabilities | None = None,
    ) -> AgentExecutionResult: ...


@dataclass(frozen=True, slots=True)
class StepOutcome:
    instance_id: str
    output: Mapping[str, object] | None
    error: AgentRuntimeError | None
    attempt: int
    cancelled: bool = False
    paused: bool = False
    best_effort: bool = False

    @property
    def succeeded(self) -> bool:
        return (
            self.output is not None
            and self.error is None
            and not self.cancelled
            and not self.paused
        )


@dataclass(frozen=True, slots=True)
class LoopContext:
    iteration: int
    current: Mapping[str, Mapping[str, object]]
    previous: Mapping[str, Mapping[str, object]]


def _descend(value: object, parts: list[str], reference: str) -> object:
    current = value
    for part in parts:
        if not isinstance(current, Mapping) or part not in current:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Interpolation reference is unavailable: {reference}",
                details={"reference": reference},
            )
        current = current[part]
    return current


class StepRunner:
    def __init__(
        self,
        *,
        plan: ExecutionPlan,
        run_id: str,
        adapter: AgentAdapter,
        capabilities: GigaCodeCapabilities,
        states: StateStore,
        events: EventLog,
        artifacts: ArtifactStore,
    ) -> None:
        self._plan = plan
        self._run_id = run_id
        self._adapter = adapter
        self._capabilities = capabilities
        self._states = states
        self._events = events
        self._artifacts = artifacts

    def _resolve(
        self,
        reference: str,
        loop: LoopContext | None = None,
    ) -> object:
        parts = reference.split(".")
        if parts[0] == "inputs":
            return _descend(self._plan.inputs, parts[1:], reference)
        if parts[:1] == ["steps"] and len(parts) >= 3 and parts[2] == "output":
            step = self._states.read(self._run_id).steps.get(parts[1])
            if step is None or step.output is None:
                raise AgentRuntimeError(
                    ErrorCode.SCENARIO_INVALID,
                    f"Step output is unavailable: {parts[1]}",
                    details={"reference": reference},
                )
            return _descend(step.output, parts[3:], reference)
        if parts == ["run", "id"]:
            return self._run_id
        if parts == ["workspace", "root"]:
            return str(self._plan.workspace)
        if parts == ["loop", "iteration"] and loop is not None:
            return loop.iteration
        if (
            len(parts) >= 4
            and parts[0] == "loop"
            and parts[1] in {"steps", "previous", "previous_or_initial"}
            and parts[3] == "output"
            and loop is not None
        ):
            name = parts[2]
            if parts[1] == "steps":
                source = loop.current
            elif parts[1] == "previous":
                source = loop.previous
            else:
                source = loop.previous
                if name not in source:
                    top_level = self._states.read(self._run_id).steps.get(name)
                    if top_level is not None and top_level.output is not None:
                        return _descend(top_level.output, parts[4:], reference)
            if name not in source:
                raise AgentRuntimeError(
                    ErrorCode.SCENARIO_INVALID,
                    f"Loop output is unavailable: {name}",
                    details={"reference": reference},
                )
            return _descend(source[name], parts[4:], reference)
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            f"Interpolation reference is unavailable: {reference}",
            details={"reference": reference},
        )

    def resolve_reference(
        self,
        reference: str,
        *,
        loop_context: LoopContext | None = None,
    ) -> object:
        return self._resolve(reference, loop_context)

    def _render_prompt(
        self,
        step: AgentStepDefinition,
        loop: LoopContext | None,
    ) -> str:
        def resolve(reference: str) -> object:
            return self._resolve(reference, loop)

        rendered = interpolate(step.prompt.template, resolve)
        prompt = rendered if isinstance(rendered, str) else canonical_json(rendered)
        if step.prompt.context:
            context = {
                key: (
                    interpolate(value, resolve)
                    if isinstance(value, str)
                    else value
                )
                for key, value in step.prompt.context.items()
            }
            prompt = f"{prompt}\n\nContext:\n{canonical_json(context)}"
        return prompt

    def mark_ready(self, step: AgentStepDefinition, *, iteration: int | None = None) -> None:
        instance_id = (
            step.name if iteration is None else f"{step.name}@iteration-{iteration}"
        )
        self._states.put_step(
            self._run_id,
            StepState(
                instance_id=instance_id,
                status=StepStatus.READY,
                iteration=iteration,
            ),
        )
        self._events.append(
            "step.ready",
            {"step": step.name, "iteration": iteration},
            step_instance_id=instance_id,
        )

    def mark_skipped(
        self,
        step: AgentStepDefinition,
        *,
        iteration: int | None = None,
    ) -> None:
        instance_id = (
            step.name if iteration is None else f"{step.name}@iteration-{iteration}"
        )
        self._states.put_step(
            self._run_id,
            StepState(
                instance_id=instance_id,
                status=StepStatus.SKIPPED,
                iteration=iteration,
            ),
        )
        self._events.append(
            "step.skipped",
            {"step": step.name, "iteration": iteration},
            step_instance_id=instance_id,
        )

    async def run(
        self,
        step: AgentStepDefinition,
        *,
        iteration: int | None = None,
        loop_context: LoopContext | None = None,
    ) -> StepOutcome:
        instance_id = (
            step.name if iteration is None else f"{step.name}@iteration-{iteration}"
        )
        agent = self._plan.agents[step.agent]
        for attempt in range(1, step.retry.max_attempts + 1):
            self._states.put_step(
                self._run_id,
                StepState(
                    instance_id=instance_id,
                    status=StepStatus.RUNNING,
                    attempt=attempt,
                    iteration=iteration,
                ),
            )
            self._events.append(
                "step.started",
                {
                    "step": step.name,
                    "agent": agent.name,
                    "model": agent.model,
                    "attempt": attempt,
                    "iteration": iteration,
                },
                step_instance_id=instance_id,
            )
            try:
                result = await self._adapter.run_agent(
                    AgentRequest(
                        model=agent.model,
                        system_prompt=agent.system_prompt,
                        prompt=self._render_prompt(step, loop_context),
                        permission=agent.permissions,
                        allowed_tools=agent.allowed_tools,
                        workspace=self._plan.workspace,
                        output_schema=step.output_schema,
                    ),
                    timeout_seconds=step.timeout_seconds
                    if step.timeout_seconds is not None
                    else 900,
                    capabilities=self._capabilities,
                )
            except anyio.get_cancelled_exc_class():
                self._states.put_step(
                    self._run_id,
                    StepState(
                        instance_id=instance_id,
                        status=StepStatus.CANCELLED,
                        attempt=attempt,
                        iteration=iteration,
                    ),
                )
                self._events.append(
                    "step.cancelled",
                    {"step": step.name, "attempt": attempt, "iteration": iteration},
                    step_instance_id=instance_id,
                )
                return StepOutcome(
                    instance_id=instance_id,
                    output=None,
                    error=None,
                    attempt=attempt,
                    cancelled=True,
                )
            except AgentRuntimeError as error:
                failure = classify_failure(error)
                if should_retry(
                    step.retry,
                    failure=failure,
                    completed_attempt=attempt,
                ):
                    delay = retry_delay(step.retry, completed_attempt=attempt)
                    self._states.put_step(
                        self._run_id,
                        StepState(
                            instance_id=instance_id,
                            status=StepStatus.RETRYING,
                            attempt=attempt,
                            iteration=iteration,
                            error=error.to_dict(),
                        ),
                    )
                    self._events.append(
                        "step.retrying",
                        {
                            "step": step.name,
                            "attempt": attempt,
                            "failure": failure.value,
                            "backoff_seconds": delay,
                            "iteration": iteration,
                        },
                        step_instance_id=instance_id,
                    )
                    if delay:
                        await anyio.sleep(delay)
                    continue
                self._states.put_step(
                    self._run_id,
                    StepState(
                        instance_id=instance_id,
                        status=StepStatus.FAILED,
                        attempt=attempt,
                        iteration=iteration,
                        error=error.to_dict(),
                    ),
                )
                self._events.append(
                    "step.failed",
                    {
                        "step": step.name,
                        "attempt": attempt,
                        "failure": failure.value,
                        "error": error.to_dict(),
                        "iteration": iteration,
                    },
                    step_instance_id=instance_id,
                )
                return StepOutcome(instance_id, None, error, attempt)

            self._artifacts.write_text(
                f"steps/{instance_id}/attempt-{attempt}/result.json",
                f"{canonical_json(result.output)}\n",
                mime_type="application/json",
            )
            if result.process.stderr:
                self._artifacts.write_text(
                    f"steps/{instance_id}/attempt-{attempt}/stderr.txt",
                    result.process.stderr,
                    mime_type="text/plain",
                )
            output = dict(result.output)
            self._states.put_step(
                self._run_id,
                StepState(
                    instance_id=instance_id,
                    status=StepStatus.COMPLETED,
                    attempt=attempt,
                    iteration=iteration,
                    output=output,
                ),
            )
            self._events.append(
                "step.completed",
                {
                    "step": step.name,
                    "attempt": attempt,
                    "iteration": iteration,
                    "duration_seconds": result.process.duration_seconds,
                },
                step_instance_id=instance_id,
            )
            return StepOutcome(instance_id, output, None, attempt)
        raise AssertionError("retry loop exhausted without a terminal outcome")
