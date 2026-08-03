from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.release_tool import verify_zip

ROOT = Path(__file__).parents[2]


def _release_archive() -> Path:
    configured = os.environ.get("GIGACODE_AGENT_RUNTIME_RELEASE_ZIP")
    candidates = (
        [Path(configured)]
        if configured
        else sorted((ROOT / "dist").glob("gigacode-agent-runtime-*-macos-x86_64.zip"))
    )
    if not candidates:
        pytest.skip("build the offline release before running ZIP acceptance")
    archive = candidates[-1].resolve()
    assert archive.is_file()
    return archive


def test_release_wheelhouses_resolve_fully_without_an_index(
    tmp_path: Path,
) -> None:
    archive = _release_archive()
    checksum_path = archive.with_name(f"{archive.name}.sha256")
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
    manifest = verify_zip(archive)
    assert manifest["release_stage"] == "release-candidate"

    with zipfile.ZipFile(archive) as release_zip:
        release_zip.extractall(tmp_path)
    release_root = next(path for path in tmp_path.iterdir() if path.is_dir())
    environment = os.environ.copy()
    environment.update(
        {
            "PIP_INDEX_URL": "http://127.0.0.1:9/must-not-be-used",
            "PIP_EXTRA_INDEX_URL": "http://127.0.0.1:9/must-not-be-used",
        }
    )

    for minor in ("311", "312", "313", "314"):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--dry-run",
                "--ignore-installed",
                "--no-index",
                "--only-binary=:all:",
                "--platform",
                "macosx_10_15_x86_64",
                "--implementation",
                "cp",
                "--python-version",
                f"3.{minor[-2:]}",
                "--abi",
                f"cp{minor}",
                "--target",
                str(tmp_path / f"resolve-py{minor}"),
                "--require-hashes",
                "--find-links",
                str(release_root / "wheelhouse" / "common"),
                "--find-links",
                str(release_root / "wheelhouse" / f"py{minor}"),
                "-r",
                str(release_root / "requirements" / f"runtime-py{minor}.lock"),
            ],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        combined = completed.stdout + completed.stderr
        assert "http://127.0.0.1:9" not in combined
        assert "Downloading" not in combined
