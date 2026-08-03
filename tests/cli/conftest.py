from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.helpers.fake_gigacode import FIXTURE_ROOT, FakeGigaCode

PROJECT_ROOT = Path(__file__).parents[2]


def cli_environment(tmp_path: Path, *, profile: str = "success") -> tuple[Path, dict[str, str]]:
    fake = FakeGigaCode(
        profile=profile,
        trace_file=tmp_path / "trace.jsonl",
        state_file=tmp_path / "attempt.txt",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        "schema_version: gigacode-agent-runtime/config-v1\n"
        "runtime:\n"
        f"  data_dir: {tmp_path / 'runtime-data'}\n"
        "  graceful_cancel_seconds: 1\n"
        "gigacode:\n"
        f"  executable: {FIXTURE_ROOT / 'gigacode'}\n"
        "  environment_allowlist:\n"
        "    - PATH\n"
        "    - HOME\n"
        "    - FAKE_GIGACODE_PROFILE\n"
        "    - FAKE_GIGACODE_TRACE_FILE\n"
        "    - FAKE_GIGACODE_STATE_FILE\n"
    )
    environment = {
        **os.environ,
        **fake.environment(),
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "HOME": str(tmp_path / "home"),
    }
    return config, environment


def run_cli(
    tmp_path: Path,
    *arguments: str,
    profile: str = "success",
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    config, environment = cli_environment(tmp_path, profile=profile)
    return subprocess.run(
        [
            str(PROJECT_ROOT / ".venv" / "bin" / "python"),
            "-m",
            "gigacode_agent_runtime",
            "--config",
            str(config),
            *arguments,
        ],
        text=True,
        capture_output=True,
        env=environment,
        timeout=timeout,
        check=False,
    )
