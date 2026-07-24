from __future__ import annotations

import time
from pathlib import Path

import anyio
import pytest

from gigacode_agent_runtime.run_manager import RunManager
from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.scheduler import DagScheduler
from gigacode_agent_runtime.state_store import StateStore
from tests.helpers.scheduler import scheduler_adapter, scheduler_config

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_manager_keeps_run_alive_after_submit_returns(tmp_path: Path) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )

    async with RunManager() as manager:
        manager.submit(
            prepared,
            DagScheduler(config, scheduler_adapter(tmp_path, "delayed")),
        )
        await anyio.sleep(0.05)
        assert StateStore(config.paths.runs).read(prepared.run_id).status.value in {
            "planned",
            "running",
        }
        state = await manager.wait(prepared.run_id)

    assert state.status.value == "completed"


@pytest.mark.anyio
async def test_shutdown_interrupts_run_and_leaves_no_agent_task(
    tmp_path: Path,
) -> None:
    config = scheduler_config(tmp_path)
    prepared = RuntimeService(config).start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )
    started = time.monotonic()

    async with RunManager() as manager:
        manager.submit(
            prepared,
            DagScheduler(
                config,
                scheduler_adapter(
                    tmp_path,
                    "ignore-sigterm",
                    graceful_cancel_seconds=0.05,
                ),
            ),
        )
        await anyio.sleep(0.15)

    state = StateStore(config.paths.runs).read(prepared.run_id)
    assert state.status.value == "interrupted"
    assert time.monotonic() - started < 2
    assert "run.interrupted" in [
        event.type for event in prepared.events.read().events
    ]
