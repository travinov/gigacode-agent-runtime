from __future__ import annotations

import hashlib
import os
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
    for stage in (
        "preflight",
        "venv",
        "install",
        "activate",
        "seed",
        "register",
        "verify",
    ):
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
    ["preflight", "venv", "install", "activate", "seed", "register", "verify"],
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
    versions = install_root / "versions"
    assert not versions.exists() or list(versions.iterdir()) == []
    data_dir = Path(environment["GIGACODE_AGENT_RUNTIME_DATA_DIR"])
    assert not (data_dir / "config.yaml").exists()
    assert not list((data_dir / "scenarios").glob("corporate-*.yaml"))
    agents_dir = Path(environment["HOME"]) / ".gigacode" / "agents"
    assert not (agents_dir / "business-analyst-proactive.md").exists()
    skills_dir = Path(environment["HOME"]) / ".gigacode" / "skills"
    assert not (skills_dir / "runtime-skill-probe" / "SKILL.md").exists()
    commands_dir = Path(environment["HOME"]) / ".gigacode" / "commands"
    assert not (commands_dir / "open_studio.md").exists()
    assert not (data_dir / ".open-studio-command.sha256").exists()


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
        install_root / "current" / "venv" / "bin" / "agent-runtime"
    )
    assert entrypoint.is_file()
    assert ".install-1.0.0" not in entrypoint.read_text()
    assert os.readlink(install_root / "current").startswith("versions/1.0.0-")
    data_dir = Path(environment["GIGACODE_AGENT_RUNTIME_DATA_DIR"])
    assert (data_dir / "config.yaml").read_text() == (
        ROOT / "corporate-profile" / "config.yaml"
    ).read_text()
    assert {
        path.name for path in (data_dir / "scenarios").glob("corporate-*.yaml")
    } == {
        "corporate-mixed.yaml",
        "corporate-parallel.yaml",
        "corporate-review-repair-loop.yaml",
        "corporate-sequential.yaml",
        "corporate-agent-ref.yaml",
        "corporate-skill-ref.yaml",
    }
    agents_dir = Path(environment["HOME"]) / ".gigacode" / "agents"
    assert (agents_dir / "business-analyst-proactive.md").is_file()
    skills_dir = Path(environment["HOME"]) / ".gigacode" / "skills"
    assert (skills_dir / "runtime-skill-probe" / "SKILL.md").is_file()
    command = Path(environment["HOME"]) / ".gigacode" / "commands" / (
        "open_studio.md"
    )
    assert command.read_text() == (
        ROOT / "corporate-profile" / "commands" / "open_studio.md"
    ).read_text()
    assert (data_dir / ".open-studio-command.sha256").is_file()


def test_install_preserves_existing_profile_files(tmp_path: Path) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    data_dir = Path(environment["GIGACODE_AGENT_RUNTIME_DATA_DIR"])
    config = data_dir / "config.yaml"
    scenario = data_dir / "scenarios" / "corporate-sequential.yaml"
    agent = Path(environment["HOME"]) / ".gigacode" / "agents" / (
        "business-analyst-proactive.md"
    )
    skill = (
        Path(environment["HOME"])
        / ".gigacode"
        / "skills"
        / "runtime-skill-probe"
        / "SKILL.md"
    )
    command = (
        Path(environment["HOME"])
        / ".gigacode"
        / "commands"
        / "open_studio.md"
    )
    config.parent.mkdir(parents=True)
    scenario.parent.mkdir(parents=True)
    agent.parent.mkdir(parents=True)
    skill.parent.mkdir(parents=True)
    command.parent.mkdir(parents=True)
    config.write_text("existing config\n")
    scenario.write_text("existing scenario\n")
    agent.write_text("existing agent\n")
    skill.write_text("existing Skill\n")
    command.write_text("existing command\n")

    completed = subprocess.run(
        ["sh", str(release / "installer" / "install-macos.sh")],
        env=environment,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert config.read_text() == "existing config\n"
    assert scenario.read_text() == "existing scenario\n"
    assert agent.read_text() == "existing agent\n"
    assert skill.read_text() == "existing Skill\n"
    assert command.read_text() == "existing command\n"
    assert not (data_dir / ".open-studio-command.sha256").exists()
    assert "preserved existing profile file" in completed.stdout
    assert "preserved existing GigaCode command" in completed.stdout


def test_install_seeds_simple_skills_scenario_when_dependencies_exist(
    tmp_path: Path,
) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    skills_dir = Path(environment["HOME"]) / ".gigacode" / "skills"
    for name in ("doc-review", "secure-coding"):
        skill = skills_dir / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(f"installed {name}\n")

    completed = subprocess.run(
        ["sh", str(release / "installer" / "install-macos.sh")],
        env=environment,
        text=True,
        capture_output=True,
    )

    installed = (
        Path(environment["GIGACODE_AGENT_RUNTIME_DATA_DIR"])
        / "scenarios"
        / "corporate-simple-skills.yaml"
    )
    assert completed.returncode == 0, completed.stderr
    assert installed.read_text() == (
        ROOT
        / "corporate-profile"
        / "optional-scenarios"
        / "corporate-simple-skills.yaml"
    ).read_text()
    assert "installed corporate profile file" in completed.stdout


def test_failed_install_rolls_back_seeded_simple_skills_scenario_only(
    tmp_path: Path,
) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    environment["GAR_FAIL_AFTER"] = "seed"
    skills_dir = Path(environment["HOME"]) / ".gigacode" / "skills"
    installed_skills: list[Path] = []
    for name in ("doc-review", "secure-coding"):
        skill = skills_dir / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(f"installed {name}\n")
        installed_skills.append(skill)

    completed = subprocess.run(
        ["sh", str(release / "installer" / "install-macos.sh")],
        env=environment,
        text=True,
        capture_output=True,
    )

    optional_scenario = (
        Path(environment["GIGACODE_AGENT_RUNTIME_DATA_DIR"])
        / "scenarios"
        / "corporate-simple-skills.yaml"
    )
    assert completed.returncode != 0
    assert not optional_scenario.exists()
    assert all(skill.is_file() for skill in installed_skills)


def test_open_studio_command_has_exact_custom_command_contract() -> None:
    command = (
        ROOT / "corporate-profile" / "commands" / "open_studio.md"
    ).read_text(encoding="utf-8")

    assert command.startswith("---\ndescription:")
    assert "`open_studio`" in command
    assert "gigacode-agent-runtime" in command
    assert "agent-runtime studio --open" in command
    assert "редактируй" in command


def test_install_replaces_non_runnable_version_directory(tmp_path: Path) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    install_root = Path(environment["GIGACODE_AGENT_RUNTIME_INSTALL_ROOT"])
    project_digest = hashlib.sha256(b"synthetic").hexdigest()
    entrypoint = (
        install_root
        / "versions"
        / f"1.0.0-{project_digest}"
        / "venv"
        / "bin"
        / "agent-runtime"
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


def test_install_activates_new_project_wheel_and_preserves_rollback(
    tmp_path: Path,
) -> None:
    release, fake_python, fake_gigacode = synthetic_release(tmp_path)
    environment = installer_environment(tmp_path, fake_python, fake_gigacode)
    command = ["sh", str(release / "installer" / "install-macos.sh")]
    install_root = Path(environment["GIGACODE_AGENT_RUNTIME_INSTALL_ROOT"])

    first = subprocess.run(command, env=environment, text=True, capture_output=True)
    assert first.returncode == 0, first.stderr
    first_target = os.readlink(install_root / "current")
    project_wheel = next(
        (release / "wheelhouse" / "common").glob(
            "gigacode_agent_runtime-1.0.0-*.whl"
        )
    )
    project_wheel.write_bytes(b"synthetic updated")

    second = subprocess.run(command, env=environment, text=True, capture_output=True)
    second_target = os.readlink(install_root / "current")

    assert second.returncode == 0, second.stderr
    assert second_target != first_target
    assert (install_root / first_target).is_dir()
    assert (install_root / second_target).is_dir()
    assert (install_root / "previous-target").read_text().strip() == first_target
