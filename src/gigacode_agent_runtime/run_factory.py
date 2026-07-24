"""Create durable run directories from compiled immutable inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .artifacts import ArtifactStore
from .config import EffectiveConfig
from .domain import ExecutionPlan, RunState, RunStatus
from .event_log import EventLog
from .hashing import to_primitive
from .plan_compiler import execution_plan_to_document
from .scenario_loader import LoadedScenario
from .serialization import atomic_write_json, atomic_write_text
from .state_store import StateStore


@dataclass(frozen=True, slots=True)
class PreparedRun:
    run_id: str
    run_dir: Path
    config: EffectiveConfig
    plan: ExecutionPlan
    state: RunState
    events: EventLog
    artifacts: ArtifactStore


def _yaml_snapshot(document: object) -> str:
    return yaml.safe_dump(
        to_primitive(document),
        allow_unicode=True,
        sort_keys=False,
    )


def _write_resource_snapshots(run_dir: Path, scenario: LoadedScenario) -> None:
    resource_dir = run_dir / "inputs" / "resources"
    manifest: list[dict[str, object]] = []
    for reference, resource in sorted(scenario.resources.items()):
        digest = __import__("hashlib").sha256(resource.content.encode("utf-8")).hexdigest()
        relative_snapshot = f"resources/{digest}.txt"
        atomic_write_text(run_dir / "inputs" / relative_snapshot, resource.content)
        manifest.append(
            {
                "reference": reference,
                "source_path": str(resource.path),
                "snapshot_path": relative_snapshot,
                "sha256": f"sha256:{digest}",
                "size_bytes": len(resource.content.encode("utf-8")),
            }
        )
    atomic_write_json(resource_dir / "manifest.json", {"resources": manifest})


def create_run(
    state_store: StateStore,
    *,
    scenario: LoadedScenario,
    config: EffectiveConfig,
    plan: ExecutionPlan,
) -> PreparedRun:
    state = state_store.create(plan.plan_hash)
    run_dir = state_store.run_dir(state.run_id)
    events = EventLog(run_dir, run_id=state.run_id)
    artifacts = ArtifactStore(
        run_dir,
        max_bytes=config.runtime.max_stdout_bytes_per_step,
    )
    events.append(
        "run.created",
        {
            "scenario_name": plan.metadata.name,
            "plan_hash": plan.plan_hash,
        },
    )

    atomic_write_text(
        run_dir / "scenario.snapshot.yaml",
        _yaml_snapshot(scenario.document),
    )
    atomic_write_text(
        run_dir / "effective-config.snapshot.yaml",
        _yaml_snapshot(config.to_snapshot()),
    )
    atomic_write_json(
        run_dir / "execution-plan.json",
        execution_plan_to_document(plan),
    )
    atomic_write_json(
        run_dir / "capability-requirements.json",
        {
            "plan_hash": plan.plan_hash,
            "required": list(plan.capability_requirements),
        },
    )
    atomic_write_json(run_dir / "inputs" / "input.json", plan.inputs)
    _write_resource_snapshots(run_dir, scenario)

    state = state_store.transition(state.run_id, RunStatus.PLANNED)
    events.append(
        "plan.compiled",
        {
            "plan_hash": plan.plan_hash,
            "waves": [list(wave) for wave in plan.waves],
            "max_parallel_agents": plan.max_parallel_agents,
        },
    )
    return PreparedRun(
        run_id=state.run_id,
        run_dir=run_dir,
        config=config,
        plan=plan,
        state=state,
        events=events,
        artifacts=artifacts,
    )
