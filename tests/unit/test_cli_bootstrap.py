from __future__ import annotations

import subprocess
import sys


def test_console_module_reports_version() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from gigacode_agent_runtime.cli import main; raise SystemExit(main(['--version']))",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "agent-runtime 0.1.0"
    assert completed.stderr == ""
