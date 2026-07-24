from __future__ import annotations

import pytest

from gigacode_agent_runtime.web.activity import (
    ActivityEvidence,
    ActivityStatus,
    classify_activity,
)


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (ActivityEvidence(5, 5, 100, True, False), ActivityStatus.RUNNING),
        (ActivityEvidence(20, 20, 100, True, False), ActivityStatus.SILENT),
        (
            ActivityEvidence(70, 70, 100, True, False),
            ActivityStatus.POSSIBLY_STALLED,
        ),
        (ActivityEvidence(100, 70, 100, True, False), ActivityStatus.TIMED_OUT),
        (
            ActivityEvidence(5, 5, 100, False, False),
            ActivityStatus.PROCESS_EXITED,
        ),
        (
            ActivityEvidence(5, 5, 100, True, True),
            ActivityStatus.PROCESS_EXITED,
        ),
    ],
)
def test_activity_classification_uses_process_and_time_evidence(
    evidence: ActivityEvidence,
    expected: ActivityStatus,
) -> None:
    assert classify_activity(evidence) is expected
