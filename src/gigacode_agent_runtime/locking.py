"""Advisory file locks for the macOS v1 single-host runtime."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import TracebackType

from .errors import AgentRuntimeError, ErrorCode


class FileLock:
    def __init__(self, path: Path, *, blocking: bool = False) -> None:
        self._path = path
        self._blocking = blocking
        self._descriptor: int | None = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        operation = fcntl.LOCK_EX
        if not self._blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, operation)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise AgentRuntimeError(
                ErrorCode.PLAN_CONFLICT,
                f"Runtime state is already owned by another writer: {self._path}",
                details={"lock_path": str(self._path)},
                retryable=True,
            ) from exc
        self._descriptor = descriptor

    def release(self) -> None:
        if self._descriptor is None:
            return
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self._descriptor)
            self._descriptor = None

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
