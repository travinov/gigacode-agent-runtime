"""Atomic materialized run state and crash recovery."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from .domain import RunState, RunStatus, StepState, StepStatus
from .errors import AgentRuntimeError, ErrorCode
from .locking import FileLock
from .schema_registry import validate_document
from .serialization import atomic_write_json
from .state_machine import transition_run
from .state_store_types import utc_timestamp
from .version import RUN_STATE_SCHEMA_VERSION

if TYPE_CHECKING:
    from .event_log import EventLog

_RUN_ID = re.compile(r"^run_[A-Za-z0-9_-]+$")


def _new_run_id() -> str:
    timestamp = utc_timestamp().replace("-", "").replace(":", "").replace(".", "")
    return f"run_{timestamp}_{uuid.uuid4().hex[:12]}"


def run_state_to_document(state: RunState) -> dict[str, object]:
    steps = {
        name: {
            "instance_id": step.instance_id,
            "status": step.status.value,
            "attempt": step.attempt,
            "iteration": step.iteration,
            "output": dict(step.output) if step.output is not None else None,
            "error": dict(step.error) if step.error is not None else None,
        }
        for name, step in state.steps.items()
    }
    return {
        "schema_version": state.schema_version,
        "run_id": state.run_id,
        "plan_hash": state.plan_hash,
        "status": state.status.value,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "steps": steps,
        "result": dict(state.result) if state.result is not None else None,
        "error": dict(state.error) if state.error is not None else None,
    }


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    if value is None:
        return None
    return MappingProxyType(dict(cast(Mapping[str, object], value)))


def run_state_from_document(document: Mapping[str, Any]) -> RunState:
    raw_steps = cast(Mapping[str, Mapping[str, Any]], document["steps"])
    steps = {
        name: StepState(
            instance_id=str(raw["instance_id"]),
            status=StepStatus(str(raw["status"])),
            attempt=int(raw["attempt"]),
            iteration=int(raw["iteration"]) if raw.get("iteration") is not None else None,
            output=_optional_mapping(raw.get("output")),
            error=_optional_mapping(raw.get("error")),
        )
        for name, raw in raw_steps.items()
    }
    return RunState(
        schema_version=str(document["schema_version"]),
        run_id=str(document["run_id"]),
        plan_hash=str(document["plan_hash"]),
        status=RunStatus(str(document["status"])),
        created_at=str(document["created_at"]),
        updated_at=str(document["updated_at"]),
        steps=MappingProxyType(steps),
        result=_optional_mapping(document.get("result")),
        error=_optional_mapping(document.get("error")),
    )


class StateStore:
    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir.resolve(strict=False)

    def run_dir(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise AgentRuntimeError(
                ErrorCode.RUN_NOT_FOUND,
                f"Invalid run ID: {run_id}",
                details={"run_id": run_id},
            )
        return self._runs_dir / run_id

    def _state_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run.json"

    def create(self, plan_hash: str) -> RunState:
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        for _ in range(10):
            run_id = _new_run_id()
            directory = self.run_dir(run_id)
            try:
                directory.mkdir()
            except FileExistsError:
                continue
            now = utc_timestamp()
            state = RunState(
                schema_version=RUN_STATE_SCHEMA_VERSION,
                run_id=run_id,
                plan_hash=plan_hash,
                status=RunStatus.VALIDATING,
                created_at=now,
                updated_at=now,
                steps=MappingProxyType({}),
            )
            self.write(state)
            return state
        raise AgentRuntimeError(
            ErrorCode.PLAN_CONFLICT,
            "Unable to allocate a unique run ID",
            retryable=True,
        )

    def write(self, state: RunState) -> None:
        document = run_state_to_document(state)
        validate_document("run-state-v1", document)
        atomic_write_json(self._state_path(state.run_id), document)

    def _preserve_corrupted(self, path: Path) -> Path | None:
        if not path.exists():
            return None
        forensic_name = (
            f"run.corrupt.{utc_timestamp().replace(':', '')}.{uuid.uuid4().hex}.json"
        )
        forensic = path.with_name(forensic_name)
        try:
            shutil.copy2(path, forensic)
        except OSError:
            return None
        return forensic

    def read(self, run_id: str) -> RunState:
        path = self._state_path(run_id)
        if not path.is_file():
            raise AgentRuntimeError(
                ErrorCode.RUN_NOT_FOUND,
                f"Run not found: {run_id}",
                details={"run_id": run_id},
            )
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            validate_document("run-state-v1", parsed)
            return run_state_from_document(cast(Mapping[str, Any], parsed))
        except (OSError, UnicodeError, json.JSONDecodeError, AgentRuntimeError, ValueError) as exc:
            forensic = self._preserve_corrupted(path)
            raise AgentRuntimeError(
                ErrorCode.STATE_CORRUPTED,
                f"Run state is corrupted: {run_id}",
                details={
                    "run_id": run_id,
                    "path": str(path),
                    "forensic_copy": str(forensic) if forensic is not None else None,
                },
            ) from exc

    def transition(self, run_id: str, target: RunStatus) -> RunState:
        lock_path = self.run_dir(run_id) / "state.lock"
        with FileLock(lock_path, blocking=True):
            state = self.read(run_id)
            transitioned = transition_run(state, target, updated_at=utc_timestamp())
            self.write(transitioned)
            return transitioned

    def recover_interrupted(
        self,
        run_id: str,
        event_log: EventLog | None = None,
    ) -> RunState:
        with FileLock(self.run_dir(run_id) / "writer.lock"):
            state = self.read(run_id)
            if state.status is not RunStatus.RUNNING:
                return state
            recovered = self.transition(run_id, RunStatus.INTERRUPTED)
            if event_log is not None:
                event_log.append(
                    "run.interrupted",
                    {"previous_status": RunStatus.RUNNING.value},
                )
            return recovered
