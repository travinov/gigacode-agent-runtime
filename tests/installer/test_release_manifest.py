from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.release_tool import create_manifest, verify_directory

ROOT = Path(__file__).parents[2]


def _write(path: Path, content: bytes = b"fixture") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _minimal_release(tmp_path: Path) -> Path:
    release = tmp_path / "gigacode-agent-runtime-v1.0.0-macos-x86_64"
    required = (
        "install.sh",
        "installer/install-macos.sh",
        "installer/uninstall-macos.sh",
        "installer/verify-installation.sh",
        "installer/rollback.sh",
        "installer/lib/common.sh",
        "scripts/release_tool.py",
        "README.md",
        "LICENSE",
        "optional-skill/SKILL.md",
        "corporate-profile/config.yaml",
        "corporate-profile/scenarios/corporate-sequential.yaml",
        "corporate-profile/scenarios/corporate-parallel.yaml",
        "corporate-profile/scenarios/corporate-mixed.yaml",
        "corporate-profile/scenarios/corporate-review-repair-loop.yaml",
        "corporate-profile/scenarios/corporate-agent-ref.yaml",
        "corporate-profile/agents/business-analyst-proactive.md",
        "docs/corporate-acceptance-checklist.md",
        "docs/release-checklist.md",
        "requirements/runtime-py311.lock",
        "requirements/runtime-py312.lock",
        "requirements/runtime-py313.lock",
        "requirements/runtime-py314.lock",
        "wheelhouse/common/gigacode_agent_runtime-1.0.0-py3-none-any.whl",
    )
    for relative in required:
        _write(release / relative)
    for minor in ("311", "312", "313", "314"):
        _write(
            release
            / "wheelhouse"
            / f"py{minor}"
            / f"pydantic_core-2.46.4-cp{minor}-cp{minor}-macosx_10_12_x86_64.whl"
        )
    create_manifest(release, ROOT / "release-manifest.json")
    return release


def test_source_release_manifest_and_locks_are_complete() -> None:
    manifest = json.loads((ROOT / "release-manifest.json").read_text())

    assert manifest["version"] == "1.0.0"
    assert manifest["minimum_macos_version"] == "10.15"
    assert manifest["architectures"] == ["x86_64"]
    assert manifest["python_minors"] == ["3.11", "3.12", "3.13", "3.14"]
    assert manifest["release_stage"] == "release-candidate"
    assert (ROOT / "install.sh").stat().st_mode & 0o111
    for minor in ("311", "312", "313", "314"):
        lock = (ROOT / "requirements" / f"runtime-py{minor}.lock").read_text()
        requirements = [
            line for line in lock.splitlines() if line and not line.startswith("#")
        ]
        assert len(requirements) >= 25
        assert all(" --hash=sha256:" in line for line in requirements)
        assert all(len(line.rsplit(":", 1)[1]) == 64 for line in requirements)


def test_generated_manifest_covers_every_release_file(tmp_path: Path) -> None:
    release = _minimal_release(tmp_path)

    verified = verify_directory(release)

    declared = {record["path"] for record in verified["files"]}
    actual = {
        path.relative_to(release).as_posix()
        for path in release.rglob("*")
        if path.is_file() and path.name != "release-manifest.json"
    }
    assert declared == actual


def test_manifest_detects_extra_or_modified_file(tmp_path: Path) -> None:
    release = _minimal_release(tmp_path)
    (release / "README.md").write_text("modified")

    with pytest.raises(ValueError, match="mismatch"):
        verify_directory(release)

    create_manifest(release, ROOT / "release-manifest.json")
    _write(release / "undeclared.txt")
    with pytest.raises(ValueError, match="coverage"):
        verify_directory(release)


def test_lock_hashes_match_bootstrapped_wheels_when_present() -> None:
    bootstrap = Path("/private/tmp/gar-lock-bootstrap.xCxRS3")
    if not bootstrap.is_dir():
        pytest.skip("bootstrap wheel cache is not available")
    for minor in ("311", "312", "313", "314"):
        lock = (ROOT / "requirements" / f"runtime-py{minor}.lock").read_text()
        wheel_hashes = {
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (bootstrap / f"py{minor}").glob("*.whl")
            if not path.name.startswith("gigacode_agent_runtime-")
        }
        declared = {
            line.rsplit(":", 1)[1]
            for line in lock.splitlines()
            if " --hash=sha256:" in line
        }
        assert declared == wheel_hashes
