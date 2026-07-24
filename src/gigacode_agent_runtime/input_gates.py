"""Typed durable human-input gates for MCP and Web control surfaces."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator

from .domain import RunStatus
from .errors import AgentRuntimeError, ErrorCode
from .event_log import EventLog
from .locking import FileLock
from .serialization import atomic_write_json
from .state_store import StateStore
from .state_store_types import utc_timestamp

_GATE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class InputGateStore:
    def __init__(self, runs_dir: Path, run_id: str) -> None:
        self._states = StateStore(runs_dir)
        self._run_id = run_id
        self._run_dir = self._states.run_dir(run_id)
        self._path = self._run_dir / "input-gates.json"
        self._lock_path = self._run_dir / "input-gates.lock"
        self._events = EventLog(self._run_dir, run_id=run_id)

    def _load_unlocked(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AgentRuntimeError(
                ErrorCode.STATE_CORRUPTED,
                "Input gate state is corrupted",
                details={"path": str(self._path)},
            ) from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("gates"), dict):
            raise AgentRuntimeError(
                ErrorCode.STATE_CORRUPTED,
                "Input gate state has an invalid shape",
                details={"path": str(self._path)},
            )
        return {
            str(key): dict(cast(Mapping[str, object], value))
            for key, value in cast(Mapping[str, object], parsed["gates"]).items()
            if isinstance(value, Mapping)
        }

    @staticmethod
    def _validate_gate_id(gate_id: str) -> None:
        if not _GATE_ID.fullmatch(gate_id):
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                f"Invalid input gate ID: {gate_id}",
                details={"gate_id": gate_id},
            )

    def request(
        self,
        gate_id: str,
        *,
        prompt: str,
        input_schema: Mapping[str, object],
    ) -> None:
        self._validate_gate_id(gate_id)
        state = self._states.read(self._run_id)
        if state.status is not RunStatus.RUNNING:
            raise AgentRuntimeError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "Input can only be requested by a running run",
                details={"status": state.status.value, "gate_id": gate_id},
            )
        with FileLock(self._lock_path, blocking=True):
            gates = self._load_unlocked()
            active = [
                name
                for name, gate in gates.items()
                if gate.get("status") == "waiting"
            ]
            if active:
                raise AgentRuntimeError(
                    ErrorCode.PLAN_CONFLICT,
                    "Another input gate is already active",
                    details={"active_gate": active[0]},
                )
            gates[gate_id] = {
                "gate_id": gate_id,
                "status": "waiting",
                "prompt": prompt,
                "input_schema": dict(input_schema),
                "requested_at": utc_timestamp(),
            }
            atomic_write_json(self._path, {"gates": gates})
        self._states.transition(self._run_id, RunStatus.WAITING_FOR_INPUT)
        self._events.append(
            "input.requested",
            {
                "gate_id": gate_id,
                "prompt": prompt,
                "input_schema": dict(input_schema),
            },
        )

    def provide(self, gate_id: str, value: object) -> dict[str, object]:
        self._validate_gate_id(gate_id)
        state = self._states.read(self._run_id)
        if state.status is not RunStatus.WAITING_FOR_INPUT:
            raise AgentRuntimeError(
                ErrorCode.INPUT_NOT_EXPECTED,
                "Run is not waiting for input",
                details={"run_id": self._run_id, "status": state.status.value},
            )
        with FileLock(self._lock_path, blocking=True):
            gates = self._load_unlocked()
            gate = gates.get(gate_id)
            if gate is None or gate.get("status") != "waiting":
                raise AgentRuntimeError(
                    ErrorCode.INPUT_NOT_EXPECTED,
                    f"Input gate is not active: {gate_id}",
                    details={"gate_id": gate_id},
                )
            schema = gate.get("input_schema")
            if not isinstance(schema, Mapping):
                raise AgentRuntimeError(
                    ErrorCode.STATE_CORRUPTED,
                    "Input gate schema is missing",
                    details={"gate_id": gate_id},
                )
            errors = sorted(
                Draft202012Validator(schema).iter_errors(value),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
            if errors:
                error = errors[0]
                raise AgentRuntimeError(
                    ErrorCode.SCHEMA_INVALID,
                    f"Provided input is invalid: {error.message}",
                    details={
                        "gate_id": gate_id,
                        "path": "/" + "/".join(
                            str(part) for part in error.absolute_path
                        ),
                    },
                )
            provided_at = utc_timestamp()
            gate["status"] = "provided"
            gate["provided_at"] = provided_at
            gates[gate_id] = gate
            atomic_write_json(
                self._run_dir / "inputs" / "provided" / f"{gate_id}.json",
                {"gate_id": gate_id, "value": value, "provided_at": provided_at},
            )
            atomic_write_json(self._path, {"gates": gates})
        self._states.transition(self._run_id, RunStatus.RUNNING)
        self._events.append(
            "input.provided",
            {"gate_id": gate_id},
        )
        return {"gate_id": gate_id, "value": value}
