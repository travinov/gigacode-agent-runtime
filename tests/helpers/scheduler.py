from __future__ import annotations

import json
from pathlib import Path

from gigacode_agent_runtime.adapters.gigacode_qwen import GigaCodeQwenAdapter
from gigacode_agent_runtime.config import EffectiveConfig, load_config
from tests.helpers.fake_gigacode import FakeGigaCode

FAKE_ENV_NAMES = (
    "PATH",
    "FAKE_GIGACODE_PROFILE",
    "FAKE_GIGACODE_TRACE_FILE",
    "FAKE_GIGACODE_STATE_FILE",
)


def scheduler_config(
    tmp_path: Path,
    *,
    max_parallel: int = 4,
    allow_full_access: bool = False,
    max_parallel_full_access: int = 1,
) -> EffectiveConfig:
    config_path = tmp_path / "runtime-config.yaml"
    config_path.write_text(
        "schema_version: gigacode-agent-runtime/config-v1\n"
        "runtime:\n"
        f"  max_parallel_agents: {max_parallel}\n"
        "  graceful_cancel_seconds: 1\n"
        "permissions:\n"
        f"  allow_full_access: {str(allow_full_access).lower()}\n"
        f"  max_parallel_full_access_agents: {max_parallel_full_access}\n"
    )
    return load_config(config_path, home=tmp_path / "home")


def scheduler_adapter(
    tmp_path: Path,
    profile: str,
    *,
    graceful_cancel_seconds: float = 0.1,
) -> GigaCodeQwenAdapter:
    fake = FakeGigaCode(
        profile=profile,
        trace_file=tmp_path / "trace.jsonl",
        state_file=tmp_path / "attempt.txt",
    )
    return GigaCodeQwenAdapter(
        executable=fake.executable,
        environment_allowlist=FAKE_ENV_NAMES,
        source_environment=fake.environment(),
        max_stdout_bytes=1024 * 1024,
        max_stderr_bytes=1024 * 1024,
        graceful_cancel_seconds=graceful_cancel_seconds,
    )


def agent_traces(tmp_path: Path) -> list[dict[str, object]]:
    path = tmp_path / "trace.jsonl"
    if not path.exists():
        return []
    traces = [json.loads(line) for line in path.read_text().splitlines()]
    return [trace for trace in traces if "--model" in trace["argv"]]
