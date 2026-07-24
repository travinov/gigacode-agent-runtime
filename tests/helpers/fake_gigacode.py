from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "fake_gigacode"


@dataclass(frozen=True, slots=True)
class FakeGigaCode:
    profile: str
    trace_file: Path
    state_file: Path

    @property
    def executable(self) -> Path:
        return FIXTURE_ROOT / "gigacode"

    def environment(self) -> dict[str, str]:
        return {
            **os.environ,
            "FAKE_GIGACODE_PROFILE": str(FIXTURE_ROOT / "profiles" / f"{self.profile}.json"),
            "FAKE_GIGACODE_TRACE_FILE": str(self.trace_file),
            "FAKE_GIGACODE_STATE_FILE": str(self.state_file),
        }
