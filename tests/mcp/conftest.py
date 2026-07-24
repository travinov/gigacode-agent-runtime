from __future__ import annotations

from pathlib import Path

import anyio


async def wait_for_status(
    tools,
    run_id: str,
    expected: set[str],
    *,
    timeout: float = 5,
) -> dict[str, object]:
    with anyio.fail_after(timeout):
        while True:
            response = await tools.get_run_status(run_id)
            assert response["ok"] is True
            state = response["data"]
            assert isinstance(state, dict)
            if state["status"] in expected:
                return state
            await anyio.sleep(0.02)


def write_project_scenario(directory: Path, source: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / source.name
    target.write_text(source.read_text())
    return target
