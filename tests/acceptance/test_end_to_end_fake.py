from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from gigacode_agent_runtime.mcp_server import TOOL_NAMES
from tests.helpers.fake_gigacode import FakeGigaCode
from tests.helpers.scheduler import agent_traces

ROOT = Path(__file__).parents[2]
SCENARIOS = ROOT / "tests" / "fixtures" / "scenarios"


def _response_data(result: Any) -> dict[str, Any]:
    document = cast(dict[str, Any] | None, result.structuredContent)
    assert document is not None
    assert document["ok"] is True
    return cast(dict[str, Any], document["data"])


@pytest.mark.anyio
async def test_real_stdio_mcp_runs_parallel_dag_with_clean_protocol(
    tmp_path: Path,
) -> None:
    fake = FakeGigaCode(
        profile="delayed",
        trace_file=tmp_path / "trace.jsonl",
        state_file=tmp_path / "attempt.txt",
    )
    config_path = tmp_path / "runtime-config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "gigacode-agent-runtime/config-v1",
                "runtime": {
                    "data_dir": str(tmp_path / "runtime data"),
                    "max_parallel_agents": 2,
                    "graceful_cancel_seconds": 1,
                },
                "gigacode": {
                    "executable": str(fake.executable),
                    "environment_allowlist": [
                        "PATH",
                        "FAKE_GIGACODE_PROFILE",
                        "FAKE_GIGACODE_TRACE_FILE",
                        "FAKE_GIGACODE_STATE_FILE",
                    ],
                },
                "web": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    environment = fake.environment()
    environment.update(
        {
            "HOME": str(tmp_path / "home"),
            "PYTHONPATH": str(ROOT / "src"),
        }
    )
    stderr_path = tmp_path / "mcp-stderr.log"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "gigacode_agent_runtime",
            "--config",
            str(config_path),
            "mcp-serve",
        ],
        env={name: str(value) for name, value in environment.items()},
        cwd=ROOT,
    )

    with stderr_path.open("w+", encoding="utf-8") as stderr_log:
        async with (
            stdio_client(parameters, errlog=stderr_log) as streams,
            ClientSession(*streams) as session,
        ):
            initialized = await session.initialize()
            discovered = await session.list_tools()
            started = await session.call_tool(
                "start_run",
                arguments={
                    "inline_scenario_yaml": (
                        SCENARIOS / "parallel-valid.yaml"
                    ).read_text(encoding="utf-8"),
                    "inputs_yaml": "task: release acceptance\n",
                    "workspace": str(tmp_path),
                    "idempotency_key": "acceptance-parallel",
                },
            )
            run_id = str(_response_data(started)["run_id"])
            with anyio.fail_after(10):
                while True:
                    status = _response_data(
                        await session.call_tool(
                            "get_run_status",
                            arguments={"run_id": run_id},
                        )
                    )
                    if status["status"] == "completed":
                        break
                    await anyio.sleep(0.02)
            result = _response_data(
                await session.call_tool(
                    "get_run_result",
                    arguments={"run_id": run_id},
                )
            )
        stderr_log.seek(0)
        stderr_output = stderr_log.read()

    traces = agent_traces(tmp_path)
    first_wave = sorted(traces[:2], key=lambda item: item["start_monotonic"])
    assert initialized.serverInfo.name == "GigaCode Agent Runtime"
    assert [tool.name for tool in discovered.tools] == list(TOOL_NAMES)
    assert result["result"]["summary"] == "delayed success"
    assert len(traces) == 3
    assert first_wave[1]["start_monotonic"] < first_wave[0]["end_monotonic"]
    assert traces[2]["start_monotonic"] >= max(
        trace["end_monotonic"] for trace in traces[:2]
    )
    assert "Traceback" not in stderr_output
