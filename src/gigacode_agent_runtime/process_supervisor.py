"""Bounded async subprocess execution with process-group cancellation."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    forced_kill: bool
    pid: int
    pgid: int
    duration_seconds: float


async def _read_limited(
    stream: asyncio.StreamReader,
    limit: int,
) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    captured = 0
    truncated = False
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            break
        remaining = max(0, limit - captured)
        if remaining:
            chunks.append(chunk[:remaining])
            captured += min(len(chunk), remaining)
        if len(chunk) > remaining:
            truncated = True
    return b"".join(chunks), truncated


async def _terminate_process_group(
    process: asyncio.subprocess.Process,
    graceful_seconds: float,
) -> bool:
    if process.returncode is not None:
        return False
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    try:
        await asyncio.wait_for(process.wait(), timeout=graceful_seconds)
        return False
    except TimeoutError:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
        return True


class ProcessSupervisor:
    def __init__(
        self,
        *,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
        graceful_cancel_seconds: float,
    ) -> None:
        self._max_stdout_bytes = max_stdout_bytes
        self._max_stderr_bytes = max_stderr_bytes
        self._graceful_cancel_seconds = graceful_cancel_seconds

    async def run(
        self,
        argv: Sequence[str | os.PathLike[str]],
        *,
        input_text: str,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
    ) -> ProcessResult:
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *(os.fspath(argument) for argument in argv),
            cwd=cwd,
            env=dict(environment),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        assert process.stdin is not None
        stdout_task = asyncio.create_task(
            _read_limited(process.stdout, self._max_stdout_bytes)
        )
        stderr_task = asyncio.create_task(
            _read_limited(process.stderr, self._max_stderr_bytes)
        )
        process.stdin.write(input_text.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()

        timed_out = False
        forced_kill = False
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
        except TimeoutError:
            timed_out = True
            forced_kill = await _terminate_process_group(
                process,
                self._graceful_cancel_seconds,
            )
        except asyncio.CancelledError:
            await _terminate_process_group(process, self._graceful_cancel_seconds)
            raise

        stdout_result, stderr_result = await asyncio.gather(stdout_task, stderr_task)
        stdout_bytes, stdout_truncated = stdout_result
        stderr_bytes, stderr_truncated = stderr_result
        return ProcessResult(
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            timed_out=timed_out,
            forced_kill=forced_kill,
            pid=process.pid,
            pgid=process.pid,
            duration_seconds=time.monotonic() - started,
        )
