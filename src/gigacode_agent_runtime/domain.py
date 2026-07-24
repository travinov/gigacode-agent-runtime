"""Immutable domain records used by the runtime core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class RunStatus(StrEnum):
    VALIDATING = "validating"
    PLANNED = "planned"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    PAUSED = "paused"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    COMPLETED_BEST_EFFORT = "completed_best_effort"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRYING = "retrying"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PermissionMode(StrEnum):
    READ_ONLY = "read_only"
    PROPOSE_ONLY = "propose_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS = "full_access"


class OnLimit(StrEnum):
    FAIL = "fail"
    PAUSE = "pause"
    BEST_EFFORT = "best_effort"


class FailureReason(StrEnum):
    PROCESS_ERROR = "process_error"
    TRANSIENT_CLI_ERROR = "transient_cli_error"
    INVALID_OUTPUT = "invalid_output"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    CONDITION_ERROR = "condition_error"
    LOOP_LIMIT = "loop_limit"
    NO_PROGRESS = "no_progress"
    PERMISSION_DENIED = "permission_denied"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: tuple[float, ...] = ()
    retry_on: tuple[FailureReason, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioMetadata:
    name: str
    title: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    name: str
    model: str
    permissions: PermissionMode
    system_prompt: str
    allowed_tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    template: str
    context: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentStepDefinition:
    name: str
    agent: str
    needs: tuple[str, ...]
    prompt: PromptDefinition
    output_schema: Mapping[str, object]
    timeout_seconds: int | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    condition: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class LoopStepDefinition:
    name: str
    needs: tuple[str, ...]
    body: tuple[AgentStepDefinition, ...]
    waves: tuple[tuple[str, ...], ...]
    until: Mapping[str, object]
    max_iterations: int
    timeout_seconds: int
    on_limit: OnLimit
    no_progress: Mapping[str, object] | None = None


ExecutionStepDefinition = AgentStepDefinition | LoopStepDefinition


@dataclass(frozen=True, slots=True)
class ScenarioSource:
    level: str
    path: Path
    root: Path


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    schema_version: str
    plan_hash: str
    scenario_hash: str
    config_hash: str
    inputs_hash: str
    metadata: ScenarioMetadata
    source: ScenarioSource
    workspace: Path
    inputs: Mapping[str, object]
    agents: Mapping[str, AgentDefinition]
    steps: tuple[ExecutionStepDefinition, ...]
    waves: tuple[tuple[str, ...], ...]
    max_parallel_agents: int
    result_reference: str
    resource_hashes: Mapping[str, str] = field(default_factory=dict)
    capability_requirements: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StepState:
    instance_id: str
    status: StepStatus
    attempt: int = 0
    iteration: int | None = None
    output: Mapping[str, object] | None = None
    error: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class RunState:
    schema_version: str
    run_id: str
    plan_hash: str
    status: RunStatus
    created_at: str
    updated_at: str
    steps: Mapping[str, StepState] = field(default_factory=dict)
    result: Mapping[str, object] | None = None
    error: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class RunEvent:
    schema_version: str
    event_id: int
    timestamp: str
    run_id: str
    type: str
    payload: Mapping[str, object]
    step_instance_id: str | None = None
