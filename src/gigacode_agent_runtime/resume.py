"""Open a run exclusively from its authenticated immutable snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from .artifacts import ArtifactStore
from .config import EffectiveConfig, load_config
from .domain import RunStatus
from .errors import AgentRuntimeError, ErrorCode
from .event_log import EventLog
from .plan_compiler import execution_plan_from_document
from .run_factory import PreparedRun
from .state_store import StateStore


def open_prepared_run(
    current_config: EffectiveConfig,
    run_id: str,
    *,
    recover_running: bool = True,
) -> PreparedRun:
    states = StateStore(current_config.paths.runs)
    run_dir = states.run_dir(run_id)
    events = EventLog(run_dir, run_id=run_id)
    state = states.read(run_id)
    if state.status is RunStatus.RUNNING and recover_running:
        state = states.recover_interrupted(run_id, events)

    plan_path = run_dir / "execution-plan.json"
    try:
        parsed = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AgentRuntimeError(
            ErrorCode.STATE_CORRUPTED,
            "Execution plan snapshot cannot be read",
            details={"path": str(plan_path)},
        ) from exc
    if not isinstance(parsed, Mapping):
        raise AgentRuntimeError(
            ErrorCode.STATE_CORRUPTED,
            "Execution plan snapshot must be an object",
            details={"path": str(plan_path)},
        )
    plan = execution_plan_from_document(cast(Mapping[str, Any], parsed))
    if state.plan_hash != plan.plan_hash:
        raise AgentRuntimeError(
            ErrorCode.STATE_CORRUPTED,
            "Run state and execution plan hashes differ",
            details={
                "state_plan_hash": state.plan_hash,
                "snapshot_plan_hash": plan.plan_hash,
            },
        )

    config_path = run_dir / "effective-config.snapshot.yaml"
    original_config = load_config(config_path, home=current_config.paths.home)
    if original_config.runtime.data_dir != current_config.runtime.data_dir:
        raise AgentRuntimeError(
            ErrorCode.STATE_CORRUPTED,
            "Run configuration points to a different runtime data directory",
            details={"path": str(config_path)},
        )
    return PreparedRun(
        run_id=run_id,
        run_dir=run_dir,
        config=original_config,
        plan=plan,
        state=state,
        events=events,
        artifacts=ArtifactStore(
            run_dir,
            max_bytes=original_config.runtime.max_stdout_bytes_per_step,
        ),
    )
