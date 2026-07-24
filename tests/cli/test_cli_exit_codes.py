from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.cli.conftest import cli_environment, run_cli


@pytest.mark.parametrize(
    "arguments",
    [
        ("diagnose", "--help"),
        ("scenarios", "list", "--help"),
        ("scenario", "validate", "--help"),
        ("scenario", "plan", "--help"),
        ("run", "--help"),
        ("status", "--help"),
        ("events", "--help"),
        ("result", "--help"),
        ("resume", "--help"),
        ("cancel", "--help"),
        ("dashboard", "--help"),
        ("mcp-serve", "--help"),
    ],
)
def test_every_command_has_help(tmp_path: Path, arguments: tuple[str, ...]) -> None:
    completed = run_cli(tmp_path, *arguments)

    assert completed.returncode == 0
    assert "usage:" in completed.stdout


def test_process_failure_uses_exit_four(tmp_path: Path) -> None:
    scenario = Path(__file__).parents[1] / "fixtures" / "scenarios" / "sequential-valid.yaml"

    completed = run_cli(
        tmp_path,
        "run",
        str(scenario),
        "--workspace",
        str(tmp_path),
        "--json",
        profile="permanent",
    )

    assert completed.returncode == 4
    assert json.loads(completed.stdout)["status"] == "failed"


def test_mcp_serve_has_no_cli_banner(tmp_path: Path) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "cli-test", "version": "1"},
        },
    }
    config, environment = cli_environment(tmp_path)
    root = Path(__file__).parents[2]

    completed = subprocess.run(
        [
            str(root / ".venv" / "bin" / "python"),
            "-m",
            "gigacode_agent_runtime",
            "--config",
            str(config),
            "mcp-serve",
        ],
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        env=environment,
        timeout=10,
        check=False,
    )

    lines = [line for line in completed.stdout.splitlines() if line]
    assert completed.returncode == 0
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == 1
