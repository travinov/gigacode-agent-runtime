"""Evidence-based activity labels for the dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ActivityStatus(StrEnum):
    RUNNING = "RUNNING"
    SILENT = "SILENT"
    POSSIBLY_STALLED = "POSSIBLY_STALLED"
    TIMED_OUT = "TIMED_OUT"
    PROCESS_EXITED = "PROCESS_EXITED"


@dataclass(frozen=True, slots=True)
class ActivityEvidence:
    elapsed_seconds: float
    silence_seconds: float
    timeout_seconds: float
    pid_alive: bool
    process_exited: bool


def classify_activity(
    evidence: ActivityEvidence,
    *,
    silent_after_seconds: float = 15,
    stalled_after_seconds: float = 60,
) -> ActivityStatus:
    if evidence.process_exited or not evidence.pid_alive:
        return ActivityStatus.PROCESS_EXITED
    if evidence.elapsed_seconds >= evidence.timeout_seconds:
        return ActivityStatus.TIMED_OUT
    if evidence.silence_seconds <= silent_after_seconds:
        return ActivityStatus.RUNNING
    if evidence.silence_seconds <= stalled_after_seconds:
        return ActivityStatus.SILENT
    return ActivityStatus.POSSIBLY_STALLED
