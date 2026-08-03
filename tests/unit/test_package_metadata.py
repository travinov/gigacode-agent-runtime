from __future__ import annotations

import subprocess
import sys


def test_package_exposes_a_semantic_version() -> None:
    from gigacode_agent_runtime import __version__

    major, minor, patch = __version__.split(".")
    assert (major, minor, patch) == ("1", "0", "0")


def test_module_version_does_not_start_runtime_services() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "gigacode_agent_runtime", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "agent-runtime 1.0.0"
    assert completed.stderr == ""
