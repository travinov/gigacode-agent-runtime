from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.installer.helpers import (
    installer_environment,
    make_executable,
    synthetic_release,
)

ROOT = Path(__file__).parents[2]


def test_installer_shell_contract_and_syntax() -> None:
    install = (ROOT / "installer" / "install-macos.sh").read_text()
    common = (ROOT / "installer" / "lib" / "common.sh").read_text()

    assert "--no-index" in install
    assert "--require-hashes" in install
    assert "--trust" not in install
    assert "gigacode" not in install.lower() or "gar_register_mcp" in install
    assert "mcp add --scope user --transport stdio" in common
    assert '"$GAR_MCP_NAME" "$GAR_LAUNCHER" mcp-serve' in common
    assert "Darwin" in common and "x86_64" in common
    assert "eval " not in install + common
    for stage in ("preflight", "venv", "install", "activate", "register", "verify"):
        assert f"gar_fail_after {stage}" in install
    scripts = (
        ROOT / "installer" / "install-macos.sh",
        ROOT / "installer" / "uninstall-macos.sh",
        ROOT / "installer" / "verify-installation.sh",
        ROOT / "installer" / "rollback.sh",
        ROOT / "installer" / "lib" / "common.sh",
    )
    for script in scripts:
        subprocess.run(["sh", "-n", str(script)], check=True)


@pytest.mark.parametrize(
    "stage",
    ["preflight", "venv", "install", "activate", "register", "verify"],
)
def test_failure_injection_rolls_back_every_stage(
    tmp_path: Path,
    stage: str,
) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    environment["GAR_FAIL_AFTER"] = stage

    completed = subprocess.run(
        ["sh", str(release / "installer" / "install-macos.sh")],
        env=environment,
        text=True,
        capture_output=True,
    )

    install_root = Path(environment["GIGACODE_AGENT_RUNTIME_INSTALL_ROOT"])
    launcher = Path(environment["GIGACODE_AGENT_RUNTIME_BIN_DIR"]) / "agent-runtime"
    assert completed.returncode != 0
    assert not (install_root / "current").exists()
    assert not launcher.exists()
    assert not (install_root / "versions" / "1.0.0").exists()


def test_install_keeps_venv_at_created_path_and_is_idempotent(
    tmp_path: Path,
) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    command = ["sh", str(release / "installer" / "install-macos.sh")]

    first = subprocess.run(command, env=environment, text=True, capture_output=True)
    second = subprocess.run(command, env=environment, text=True, capture_output=True)

    install_root = Path(environment["GIGACODE_AGENT_RUNTIME_INSTALL_ROOT"])
    launcher = Path(environment["GIGACODE_AGENT_RUNTIME_BIN_DIR"]) / "agent-runtime"
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (install_root / "current").is_symlink()
    assert launcher.is_symlink()
    entrypoint = (
        install_root / "versions" / "1.0.0" / "venv" / "bin" / "agent-runtime"
    )
    assert entrypoint.is_file()
    assert ".install-1.0.0" not in entrypoint.read_text()


def test_install_replaces_non_runnable_version_directory(tmp_path: Path) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    install_root = Path(environment["GIGACODE_AGENT_RUNTIME_INSTALL_ROOT"])
    entrypoint = (
        install_root / "versions" / "1.0.0" / "venv" / "bin" / "agent-runtime"
    )
    make_executable(entrypoint, "#!/bin/sh\nexit 126\n")

    completed = subprocess.run(
        ["sh", str(release / "installer" / "install-macos.sh")],
        env=environment,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    version = subprocess.run(
        [str(entrypoint), "--version"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip() == "agent-runtime 1.0.0"
