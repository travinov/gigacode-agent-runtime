"""Construct the configured GigaCode/Qwen adapter."""

from __future__ import annotations

import os

from .adapters.capabilities import find_gigacode_executable
from .adapters.gigacode_qwen import GigaCodeQwenAdapter
from .config import EffectiveConfig


def create_gigacode_adapter(config: EffectiveConfig) -> GigaCodeQwenAdapter:
    executable = find_gigacode_executable(
        config.gigacode.executable,
        home=config.paths.home,
        path=os.environ.get("PATH"),
    )
    return GigaCodeQwenAdapter(
        executable=executable,
        environment_allowlist=config.gigacode.environment_allowlist,
        source_environment=os.environ,
        max_stdout_bytes=config.runtime.max_stdout_bytes_per_step,
        max_stderr_bytes=config.runtime.max_stderr_bytes_per_step,
        graceful_cancel_seconds=config.runtime.graceful_cancel_seconds,
    )
