from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.installer.helpers import (
    installer_environment,
    make_executable,
    synthetic_release,
)


def _installed_version(root: Path, version: str) -> Path:
    runtime = root / "versions" / version / "venv" / "bin" / "agent-runtime"
    make_executable(runtime, f"#!/bin/sh\necho 'agent-runtime {version}'\n")
    return runtime


def test_manual_rollback_switches_to_previous_version(tmp_path: Path) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    install_root = Path(environment["GIGACODE_AGENT_RUNTIME_INSTALL_ROOT"])
    bin_dir = Path(environment["GIGACODE_AGENT_RUNTIME_BIN_DIR"])
    _installed_version(install_root, "0.9.0")
    _installed_version(install_root, "1.0.0")
    (install_root / "current").symlink_to("versions/1.0.0")
    (install_root / "previous-target").write_text("versions/0.9.0\n")
    bin_dir.mkdir(parents=True)
    (bin_dir / "agent-runtime").symlink_to(
        install_root / "current" / "venv" / "bin" / "agent-runtime"
    )

    completed = subprocess.run(
        ["sh", str(release / "installer" / "rollback.sh")],
        env=environment,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert os.readlink(install_root / "current") == "versions/0.9.0"
    assert (install_root / "previous-target").read_text().strip() == "versions/1.0.0"


def test_uninstall_preserves_data_without_purge(tmp_path: Path) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    install_root = Path(environment["GIGACODE_AGENT_RUNTIME_INSTALL_ROOT"])
    data_dir = Path(environment["GIGACODE_AGENT_RUNTIME_DATA_DIR"])
    bin_dir = Path(environment["GIGACODE_AGENT_RUNTIME_BIN_DIR"])
    _installed_version(install_root, "1.0.0")
    (install_root / "current").symlink_to("versions/1.0.0")
    bin_dir.mkdir(parents=True)
    (bin_dir / "agent-runtime").symlink_to(
        install_root / "current" / "venv" / "bin" / "agent-runtime"
    )
    (data_dir / "runs").mkdir(parents=True)
    marker = data_dir / "runs" / "preserve.txt"
    marker.write_text("keep")

    completed = subprocess.run(
        ["sh", str(release / "installer" / "uninstall-macos.sh")],
        env=environment,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.read_text() == "keep"
    assert not install_root.exists()


def test_uninstall_removes_unchanged_installer_owned_open_studio_command(
    tmp_path: Path,
) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    install = subprocess.run(
        ["sh", str(release / "installer" / "install-macos.sh")],
        env=environment,
        text=True,
        capture_output=True,
    )
    command = Path(environment["HOME"]) / ".gigacode" / "commands" / (
        "open_studio.md"
    )
    marker = (
        Path(environment["GIGACODE_AGENT_RUNTIME_DATA_DIR"])
        / ".open-studio-command.sha256"
    )
    assert install.returncode == 0, install.stderr
    assert command.is_file() and marker.is_file()

    uninstall = subprocess.run(
        ["sh", str(release / "installer" / "uninstall-macos.sh")],
        env=environment,
        text=True,
        capture_output=True,
    )

    assert uninstall.returncode == 0, uninstall.stderr
    assert not command.exists()
    assert not marker.exists()


def test_uninstall_preserves_user_modified_open_studio_command(tmp_path: Path) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    install = subprocess.run(
        ["sh", str(release / "installer" / "install-macos.sh")],
        env=environment,
        text=True,
        capture_output=True,
    )
    command = Path(environment["HOME"]) / ".gigacode" / "commands" / (
        "open_studio.md"
    )
    marker = (
        Path(environment["GIGACODE_AGENT_RUNTIME_DATA_DIR"])
        / ".open-studio-command.sha256"
    )
    assert install.returncode == 0, install.stderr
    command.write_text("user customized command\n", encoding="utf-8")

    uninstall = subprocess.run(
        ["sh", str(release / "installer" / "uninstall-macos.sh")],
        env=environment,
        text=True,
        capture_output=True,
    )

    assert uninstall.returncode == 0, uninstall.stderr
    assert command.read_text(encoding="utf-8") == "user customized command\n"
    assert not marker.exists()
    assert "preserved modified GigaCode command" in uninstall.stdout


def test_purge_refuses_home_as_data_target(tmp_path: Path) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    home = Path(environment["HOME"])
    marker = home / "must-survive.txt"
    marker.write_text("safe")
    environment["GIGACODE_AGENT_RUNTIME_DATA_DIR"] = str(home)
    environment["GAR_CONFIRM_PURGE"] = "PURGE"

    completed = subprocess.run(
        [
            "sh",
            str(release / "installer" / "uninstall-macos.sh"),
            "--purge-data",
        ],
        env=environment,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert marker.read_text() == "safe"
