from __future__ import annotations

import re
from pathlib import Path

import pytest

from gigacode_agent_runtime.domain import RunStatus
from gigacode_agent_runtime.runtime_service import RuntimeService
from gigacode_agent_runtime.scenario_loader import load_scenario_file
from gigacode_agent_runtime.state_store import StateStore
from tests.web.conftest import authenticate, dashboard_fixture

SCENARIOS = Path(__file__).parents[1] / "fixtures" / "scenarios"


@pytest.mark.anyio
async def test_sse_reconnect_uses_last_event_id_without_duplicates(
    tmp_path: Path,
) -> None:
    tools, auth, client = dashboard_fixture(tmp_path)
    prepared = RuntimeService(tools.config).start_run(
        load_scenario_file(SCENARIOS / "sequential-valid.yaml"),
        inputs={},
        workspace=tmp_path,
    )
    prepared.events.append("run.heartbeat", {"number": 1})
    prepared.events.append("run.heartbeat", {"number": 2})
    StateStore(tools.config.paths.runs).transition(
        prepared.run_id,
        RunStatus.CANCELLED,
    )
    await authenticate(client, auth)
    try:
        first = await client.get(f"/api/runs/{prepared.run_id}/stream")
        second = await client.get(
            f"/api/runs/{prepared.run_id}/stream",
            headers={"Last-Event-ID": "2"},
        )
    finally:
        await client.aclose()

    first_ids = [int(value) for value in re.findall(r"^id: (\d+)$", first.text, re.M)]
    second_ids = [int(value) for value in re.findall(r"^id: (\d+)$", second.text, re.M)]
    assert first_ids == [1, 2, 3, 4]
    assert second_ids == [3, 4]
