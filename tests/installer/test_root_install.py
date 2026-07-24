from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from tests.installer.helpers import make_executable

ROOT = Path(__file__).parents[2]


def _release_fixture(tmp_path: Path, installer: str) -> Path:
    release = tmp_path / "release with spaces"
    release.mkdir()
    shutil.copy2(ROOT / "install.sh", release / "install.sh")
    make_executable(release / "installer" / "install-macos.sh", installer)
    return release


def test_root_installer_is_offline_and_has_valid_shell_syntax() -> None:
    content = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "installer/install-macos.sh" in content
    assert "curl" not in content
    assert "http://" not in content
    assert "https://" not in content
    subprocess.run(["sh", "-n", str(ROOT / "install.sh")], check=True)


def test_root_installer_delegates_from_directory_with_spaces(
    tmp_path: Path,
) -> None:
    release = _release_fixture(
        tmp_path,
        '#!/bin/sh\nprintf "installed\\n" > "$GAR_ROOT_INSTALL_MARKER"\n',
    )
    marker = tmp_path / "installed.txt"
    environment = os.environ.copy()
    environment["GAR_ROOT_INSTALL_MARKER"] = str(marker)

    completed = subprocess.run(
        ["sh", str(release / "install.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.read_text(encoding="utf-8") == "installed\n"


def test_root_installer_propagates_installer_failure(tmp_path: Path) -> None:
    release = _release_fixture(
        tmp_path,
        "#!/bin/sh\nexit 17\n",
    )

    completed = subprocess.run(
        ["sh", str(release / "install.sh")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 17
