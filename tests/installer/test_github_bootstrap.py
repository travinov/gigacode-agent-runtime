from __future__ import annotations

import hashlib
import os
import subprocess
import zipfile
from pathlib import Path

from tests.installer.helpers import make_executable

ROOT = Path(__file__).parents[2]


def _fake_release(tmp_path: Path) -> tuple[Path, str]:
    release_dir = tmp_path / "release"
    archive_name = "gigacode-agent-runtime-v1.0.0-macos-x86_64.zip"
    archive = release_dir / archive_name
    source = tmp_path / "source"
    installer = (
        source
        / "gigacode-agent-runtime-v1.0.0-macos-x86_64"
        / "installer"
        / "install-macos.sh"
    )
    installer.parent.mkdir(parents=True)
    installer.write_text(
        '#!/bin/sh\nprintf "installed\\n" > "$GAR_BOOTSTRAP_MARKER"\n',
        encoding="utf-8",
    )
    release_dir.mkdir()
    with zipfile.ZipFile(archive, "w") as release_zip:
        release_zip.write(
            installer,
            installer.relative_to(source).as_posix(),
        )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release_dir / f"{archive_name}.sha256").write_text(
        f"{digest}  {archive_name}\n",
        encoding="utf-8",
    )
    return release_dir, digest


def _fake_curl(path: Path) -> None:
    make_executable(
        path,
        """#!/bin/sh
set -eu
url=""
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output)
      output=$2
      shift 2
      ;;
    --*)
      shift
      ;;
    *)
      url=$1
      shift
      ;;
  esac
done
name=${url##*/}
cp "$FAKE_RELEASE_DIR/$name" "$output"
""",
    )


def test_one_line_bootstrap_verifies_release_and_runs_installer(
    tmp_path: Path,
) -> None:
    release_dir, digest = _fake_release(tmp_path)
    tools = tmp_path / "tools"
    _fake_curl(tools / "curl")
    marker = tmp_path / "installed.txt"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{tools}:{environment['PATH']}",
            "TMPDIR": str(tmp_path),
            "FAKE_RELEASE_DIR": str(release_dir),
            "GAR_BOOTSTRAP_MARKER": str(marker),
            "GAR_TEST_SYSTEM": "Darwin",
            "GAR_TEST_MACHINE": "x86_64",
            "GIGACODE_AGENT_RUNTIME_EXPECTED_SHA256": digest,
        }
    )

    completed = subprocess.run(
        ["sh", str(ROOT / "install.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.read_text(encoding="utf-8") == "installed\n"
    assert not list(tmp_path.glob("gigacode-agent-runtime-install.*"))


def test_bootstrap_rejects_checksum_not_pinned_in_script(tmp_path: Path) -> None:
    release_dir, _digest = _fake_release(tmp_path)
    tools = tmp_path / "tools"
    _fake_curl(tools / "curl")
    marker = tmp_path / "must-not-exist.txt"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{tools}:{environment['PATH']}",
            "TMPDIR": str(tmp_path),
            "FAKE_RELEASE_DIR": str(release_dir),
            "GAR_BOOTSTRAP_MARKER": str(marker),
            "GAR_TEST_SYSTEM": "Darwin",
            "GAR_TEST_MACHINE": "x86_64",
            "GIGACODE_AGENT_RUNTIME_EXPECTED_SHA256": "0" * 64,
        }
    )

    completed = subprocess.run(
        ["sh", str(ROOT / "install.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "pinned release checksum" in completed.stderr
    assert not marker.exists()
