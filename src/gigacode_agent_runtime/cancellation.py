"""Process-local cooperative execution controls."""

from __future__ import annotations

import anyio


class ExecutionControl:
    def __init__(self) -> None:
        self._stop_event = anyio.Event()
        self._stop_reason: str | None = None
        self._pause_requested = False

    @property
    def cancel_requested(self) -> bool:
        return self._stop_reason == "cancel"

    @property
    def interrupt_requested(self) -> bool:
        return self._stop_reason == "interrupt"

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    @property
    def pause_requested(self) -> bool:
        return self._pause_requested

    def cancel(self) -> None:
        if self._stop_reason is None:
            self._stop_reason = "cancel"
            self._stop_event.set()

    def interrupt(self) -> None:
        if self._stop_reason is None:
            self._stop_reason = "interrupt"
            self._stop_event.set()

    def pause(self) -> None:
        self._pause_requested = True

    async def wait_stopped(self) -> None:
        await self._stop_event.wait()
