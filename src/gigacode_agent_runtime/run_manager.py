"""Process-local owner for background run tasks and graceful shutdown."""

from __future__ import annotations

from dataclasses import dataclass

import anyio

from .cancellation import ExecutionControl
from .domain import RunState
from .errors import AgentRuntimeError, ErrorCode
from .run_factory import PreparedRun
from .scheduler import DagScheduler, SchedulerResult


@dataclass(slots=True)
class ManagedRun:
    run_id: str
    control: ExecutionControl
    done: anyio.Event
    result: SchedulerResult | None = None
    error: BaseException | None = None


class RunManager:
    """Keep submitted runs alive while the MCP/CLI process is alive."""

    def __init__(self) -> None:
        self._task_group: anyio.abc.TaskGroup | None = None
        self._runs: dict[str, ManagedRun] = {}
        self._closing = False

    async def __aenter__(self) -> RunManager:
        if self._task_group is not None:
            raise RuntimeError("RunManager is already started")
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        await self.shutdown()

    async def _execute(
        self,
        managed: ManagedRun,
        scheduler: DagScheduler,
        prepared: PreparedRun,
    ) -> None:
        try:
            managed.result = await scheduler.run(
                prepared,
                control=managed.control,
            )
        except BaseException as error:
            managed.error = error
        finally:
            managed.done.set()

    def submit(
        self,
        prepared: PreparedRun,
        scheduler: DagScheduler,
    ) -> ExecutionControl:
        if self._task_group is None or self._closing:
            raise AgentRuntimeError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "RunManager is not accepting new runs",
            )
        if prepared.run_id in self._runs:
            return self._runs[prepared.run_id].control
        managed = ManagedRun(
            run_id=prepared.run_id,
            control=ExecutionControl(),
            done=anyio.Event(),
        )
        self._runs[prepared.run_id] = managed
        self._task_group.start_soon(
            self._execute,
            managed,
            scheduler,
            prepared,
        )
        return managed.control

    def control(self, run_id: str) -> ExecutionControl:
        managed = self._runs.get(run_id)
        if managed is None:
            raise AgentRuntimeError(
                ErrorCode.RUN_NOT_FOUND,
                f"Managed run not found: {run_id}",
                details={"run_id": run_id},
            )
        return managed.control

    async def wait(self, run_id: str) -> RunState:
        managed = self._runs.get(run_id)
        if managed is None:
            raise AgentRuntimeError(
                ErrorCode.RUN_NOT_FOUND,
                f"Managed run not found: {run_id}",
                details={"run_id": run_id},
            )
        await managed.done.wait()
        if managed.error is not None:
            raise managed.error
        assert managed.result is not None
        return managed.result.state

    async def shutdown(self) -> None:
        if self._task_group is None:
            return
        self._closing = True
        active = [managed for managed in self._runs.values() if not managed.done.is_set()]
        for managed in active:
            managed.control.interrupt()
        for managed in active:
            await managed.done.wait()
        task_group = self._task_group
        self._task_group = None
        await task_group.__aexit__(None, None, None)
