"""Path-safe dashboard API over the shared runtime services."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from ..domain import StepStatus
from ..errors import AgentRuntimeError, ErrorCode
from ..event_log import EventLog
from ..input_gates import InputGateStore
from ..mcp_tools import McpToolService
from ..plan_compiler import execution_plan_to_document
from ..state_store import StateStore, run_state_to_document
from .activity import ActivityEvidence, classify_activity


def _timestamp(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC).timestamp()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


class DashboardApi:
    def __init__(self, tools: McpToolService) -> None:
        self._tools = tools
        self._states = StateStore(tools.config.paths.runs)

    def list_runs(self, *, limit: int = 100) -> dict[str, object]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        directory = self._tools.config.paths.runs
        if not directory.exists():
            return {"runs": []}
        states = []
        for path in sorted(
            directory.iterdir(),
            key=lambda item: item.name,
            reverse=True,
        ):
            if not path.is_dir():
                continue
            try:
                state = self._states.read(path.name)
            except AgentRuntimeError:
                continue
            states.append(run_state_to_document(state))
            if len(states) >= limit:
                break
        return {"runs": states}

    def status(self, run_id: str) -> dict[str, object]:
        state = self._states.read(run_id)
        document = run_state_to_document(state)
        run_dir = self._states.run_dir(run_id)
        events = EventLog(run_dir, run_id=run_id).tail(limit=1000)
        latest_process = next(
            (
                event
                for event in reversed(events)
                if event.type == "step.heartbeat"
                and event.payload.get("phase") == "process_started"
            ),
            None,
        )
        activity: dict[str, object] | None = None
        if latest_process is not None:
            pid_raw = latest_process.payload["pid"]
            if not isinstance(pid_raw, int):
                raise AgentRuntimeError(
                    ErrorCode.STATE_CORRUPTED,
                    "Process event contains an invalid PID",
                )
            pid = pid_raw
            started = _timestamp(latest_process.timestamp)
            last_event = _timestamp(events[-1].timestamp) if events else started
            now = datetime.now(UTC).timestamp()
            instance = latest_process.step_instance_id
            step = state.steps.get(instance or "")
            timeout = self._tools.config.runtime.default_step_timeout_seconds
            process_exited = (
                step is not None
                and step.status
                in {
                    StepStatus.COMPLETED,
                    StepStatus.FAILED,
                    StepStatus.CANCELLED,
                    StepStatus.INTERRUPTED,
                }
            )
            evidence = ActivityEvidence(
                elapsed_seconds=max(0, now - started),
                silence_seconds=max(0, now - last_event),
                timeout_seconds=timeout,
                pid_alive=_pid_alive(pid),
                process_exited=process_exited,
            )
            activity = {
                "status": classify_activity(evidence).value,
                "pid": pid,
                "pgid": latest_process.payload.get("pgid"),
                "elapsed_seconds": evidence.elapsed_seconds,
                "silence_seconds": evidence.silence_seconds,
            }
        document["activity"] = activity
        blocker: dict[str, object] | None = None
        if state.status.value == "waiting_for_approval":
            blocker = {
                "type": "approval",
                "plan_hash": state.plan_hash,
                "gate": "full_access",
            }
        elif state.status.value == "waiting_for_input":
            blocker = {
                "type": "input",
                **(
                    InputGateStore(
                        self._tools.config.paths.runs,
                        run_id,
                    ).active()
                    or {}
                ),
            }
        document["blocker"] = blocker
        return document

    def plan(self, run_id: str) -> dict[str, object]:
        prepared = self._tools._runtime.open_run(run_id, recover_running=False)
        document = execution_plan_to_document(prepared.plan)
        document.pop("source", None)
        document.pop("workspace", None)
        return document

    async def events(
        self,
        run_id: str,
        *,
        after: int,
        limit: int,
    ) -> dict[str, object]:
        result = await self._tools.get_run_events(run_id, after=after, limit=limit)
        return self._unwrap(result)

    async def result(self, run_id: str) -> dict[str, object]:
        response = await self._tools.get_run_result(run_id)
        return self._unwrap(response)

    async def artifacts(
        self,
        run_id: str,
        *,
        after: int,
        limit: int,
    ) -> dict[str, object]:
        response = await self._tools.get_run_artifacts(
            run_id,
            after=after,
            limit=limit,
        )
        return self._unwrap(response)

    @staticmethod
    def _unwrap(response: dict[str, object]) -> dict[str, object]:
        if response["ok"] is True:
            data = response["data"]
            assert isinstance(data, dict)
            return data
        raw = response["error"]
        assert isinstance(raw, dict)
        from ..errors import ErrorCode

        raise AgentRuntimeError(
            ErrorCode(str(raw["code"])),
            str(raw["message"]),
            details=raw.get("details") if isinstance(raw.get("details"), dict) else {},
            retryable=bool(raw.get("retryable", False)),
        )

    async def control(
        self,
        action: str,
        run_id: str,
        payload: dict[str, Any],
    ) -> dict[str, object]:
        if action == "pause":
            return self._unwrap(await self._tools.pause_run(run_id))
        if action == "resume":
            return self._unwrap(await self._tools.resume_run(run_id))
        if action == "cancel":
            return self._unwrap(await self._tools.cancel_run(run_id))
        if action == "approve":
            return self._unwrap(
                await self._tools.approve_run(
                    run_id,
                    str(payload.get("plan_hash", "")),
                    str(payload.get("gate", "full_access")),
                )
            )
        if action == "input":
            return self._unwrap(
                await self._tools.provide_input(
                    run_id,
                    str(payload.get("gate_id", "")),
                    payload.get("value"),
                )
            )
        raise ValueError(f"Unsupported control action: {action}")
