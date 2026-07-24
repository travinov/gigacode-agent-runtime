from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_stdio_stdout_contains_only_jsonrpc_frames(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    data_dir = tmp_path / "runtime-data"
    config_path.write_text(
        "schema_version: gigacode-agent-runtime/config-v1\n"
        f"runtime:\n  data_dir: {data_dir}\n"
    )
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "stdio-test", "version": "1"},
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
    ]
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parents[2] / "src"),
        "GIGACODE_AGENT_RUNTIME_CONFIG": str(config_path),
        "HOME": str(tmp_path / "home"),
    }

    completed = subprocess.run(
        [
            str(Path(__file__).parents[2] / ".venv" / "bin" / "python"),
            "-m",
            "gigacode_agent_runtime.mcp_server",
        ],
        input="".join(json.dumps(item) + "\n" for item in requests),
        text=True,
        capture_output=True,
        env=environment,
        timeout=10,
        check=False,
    )

    frames = [
        json.loads(line)
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    assert completed.returncode == 0
    assert {frame.get("id") for frame in frames} == {1, 2}
    assert all(frame["jsonrpc"] == "2.0" for frame in frames)
    assert "Traceback" not in completed.stdout
