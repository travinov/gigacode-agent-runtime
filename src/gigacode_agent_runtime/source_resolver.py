"""Resolve scenario-owned files without path or symlink escapes."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from .errors import AgentRuntimeError, ErrorCode


@dataclass(frozen=True, slots=True)
class ResolvedResource:
    reference: str
    path: Path
    content: str


class ContainedSourceResolver:
    def __init__(
        self,
        allowed_roots: tuple[Path, ...],
        *,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self._roots = tuple(root.resolve(strict=False) for root in allowed_roots)
        self._max_bytes = max_bytes

    def _resolve(self, reference: str, base_dir: Path) -> Path:
        raw = Path(reference)
        candidate = raw if raw.is_absolute() else base_dir / raw
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Referenced file does not exist: {reference}",
                details={"reference": reference},
            ) from exc

        if not any(resolved.is_relative_to(root) for root in self._roots):
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                f"Referenced path escapes allowed roots: {reference}",
                details={
                    "reference": reference,
                    "resolved_path": str(resolved),
                    "allowed_roots": [str(root) for root in self._roots],
                },
            )
        try:
            mode = resolved.stat().st_mode
        except OSError as exc:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Cannot inspect referenced file: {reference}",
                details={"reference": reference},
            ) from exc
        if not stat.S_ISREG(mode):
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                f"Referenced path is not a regular file: {reference}",
                details={"reference": reference, "resolved_path": str(resolved)},
            )
        return resolved

    def read_text(self, reference: str, *, base_dir: Path) -> ResolvedResource:
        path = self._resolve(reference, base_dir.resolve(strict=False))
        try:
            size = path.stat().st_size
            if size > self._max_bytes:
                raise AgentRuntimeError(
                    ErrorCode.SCENARIO_INVALID,
                    f"Referenced file exceeds {self._max_bytes} bytes: {reference}",
                    details={"reference": reference, "size": size},
                )
            content = path.read_text(encoding="utf-8")
        except AgentRuntimeError:
            raise
        except (OSError, UnicodeError) as exc:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Cannot read referenced UTF-8 file: {reference}",
                details={"reference": reference},
            ) from exc
        return ResolvedResource(reference=reference, path=path, content=content)
