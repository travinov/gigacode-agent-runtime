"""Filesystem locations with testable, explicit home-directory handling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def resolve_user_path(value: str, home: Path, *, base: Path | None = None) -> Path:
    """Resolve `~` against an injected home instead of ambient process state."""

    if value == "~":
        candidate = home
    elif value.startswith("~/"):
        candidate = home / value[2:]
    else:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = (base or home) / candidate
    return candidate.resolve(strict=False)


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    home: Path
    data_dir: Path
    config_file: Path
    user_scenarios: Path
    runs: Path

    @classmethod
    def for_home(cls, home: Path) -> RuntimePaths:
        resolved_home = home.resolve(strict=False)
        data_dir = resolved_home / ".gigacode" / "agent-runtime"
        return cls(
            home=resolved_home,
            data_dir=data_dir,
            config_file=data_dir / "config.yaml",
            user_scenarios=data_dir / "scenarios",
            runs=data_dir / "runs",
        )

    def with_data_dir(self, data_dir: Path) -> RuntimePaths:
        resolved = data_dir.resolve(strict=False)
        return RuntimePaths(
            home=self.home,
            data_dir=resolved,
            config_file=self.config_file,
            user_scenarios=resolved / "scenarios",
            runs=resolved / "runs",
        )
