"""Contained, checksummed output artifacts for one run."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from .errors import AgentRuntimeError, ErrorCode
from .locking import FileLock
from .serialization import atomic_write_json, atomic_write_text
from .state_store_types import utc_timestamp


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    relative_path: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: str


class ArtifactStore:
    """Write artifacts below ``<run>/artifacts`` without path traversal."""

    def __init__(self, run_dir: Path, *, max_bytes: int = 50 * 1024 * 1024) -> None:
        self._run_dir = run_dir.resolve(strict=False)
        self._root = self._run_dir / "artifacts"
        self._manifest_path = self._run_dir / "artifacts.json"
        self._lock_path = self._run_dir / "artifacts.lock"
        self._max_bytes = max_bytes

    def _target(self, relative_path: str) -> tuple[str, Path]:
        normalized = PurePosixPath(relative_path)
        if (
            not relative_path
            or normalized.is_absolute()
            or ".." in normalized.parts
            or "." in normalized.parts
        ):
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                f"Artifact path is not allowed: {relative_path}",
                details={"path": relative_path},
            )
        clean = normalized.as_posix()
        target = self._root.joinpath(*normalized.parts)
        root = self._root.resolve(strict=False)
        try:
            resolved_parent = target.parent.resolve(strict=False)
        except RuntimeError as exc:
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                f"Artifact path cannot be resolved: {relative_path}",
                details={"path": relative_path},
            ) from exc
        if not resolved_parent.is_relative_to(root):
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                f"Artifact path escapes the run: {relative_path}",
                details={"path": relative_path},
            )
        if target.exists() and target.is_symlink():
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                f"Artifact target cannot be a symlink: {relative_path}",
                details={"path": relative_path},
            )
        return clean, target

    def _load_manifest_unlocked(self) -> dict[str, object]:
        if not self._manifest_path.exists():
            return {"artifacts": []}
        try:
            parsed = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AgentRuntimeError(
                ErrorCode.STATE_CORRUPTED,
                "Artifact manifest is corrupted",
                details={"path": str(self._manifest_path)},
            ) from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("artifacts"), list):
            raise AgentRuntimeError(
                ErrorCode.STATE_CORRUPTED,
                "Artifact manifest has an invalid shape",
                details={"path": str(self._manifest_path)},
            )
        return parsed

    def write_text(
        self,
        relative_path: str,
        content: str,
        *,
        mime_type: str,
    ) -> ArtifactRecord:
        encoded = content.encode("utf-8")
        if len(encoded) > self._max_bytes:
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                "Artifact exceeds the configured size limit",
                details={
                    "path": relative_path,
                    "size_bytes": len(encoded),
                    "max_bytes": self._max_bytes,
                },
            )
        clean, target = self._target(relative_path)
        digest = hashlib.sha256(encoded).hexdigest()
        record = ArtifactRecord(
            artifact_id=f"sha256:{digest}",
            relative_path=clean,
            mime_type=mime_type,
            size_bytes=len(encoded),
            sha256=f"sha256:{digest}",
            created_at=utc_timestamp(),
        )
        with FileLock(self._lock_path, blocking=True):
            # Resolve again while holding the writer lock so a prior artifact cannot
            # replace a parent with a symlink between validation and the write.
            clean, target = self._target(clean)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.parent.resolve(strict=True).is_relative_to(
                self._root.resolve(strict=True)
            ):
                raise AgentRuntimeError(
                    ErrorCode.PATH_NOT_ALLOWED,
                    f"Artifact path escapes the run: {clean}",
                    details={"path": clean},
                )
            atomic_write_text(target, content)
            manifest = self._load_manifest_unlocked()
            artifacts = manifest["artifacts"]
            assert isinstance(artifacts, list)
            artifacts = [
                item
                for item in artifacts
                if not isinstance(item, dict) or item.get("relative_path") != clean
            ]
            artifacts.append(asdict(record))
            manifest["artifacts"] = sorted(
                artifacts,
                key=lambda item: (
                    str(item.get("relative_path", "")) if isinstance(item, dict) else ""
                ),
            )
            atomic_write_json(self._manifest_path, manifest)
        return record
