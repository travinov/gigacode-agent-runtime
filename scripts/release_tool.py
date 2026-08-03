#!/usr/bin/env python3
"""Build-time manifest, wheelhouse, and reproducible ZIP utilities."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

_MANIFEST = "release-manifest.json"
_FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_record(path: Path, root: Path) -> dict[str, object]:
    relative = path.relative_to(root).as_posix()
    content = path.read_bytes()
    return {
        "path": relative,
        "sha256": _sha256_bytes(content),
        "size_bytes": len(content),
    }


def _release_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.name != _MANIFEST
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def create_manifest(root: Path, template_path: Path) -> None:
    template = json.loads(template_path.read_text(encoding="utf-8"))
    template["files"] = [_file_record(path, root) for path in _release_files(root)]
    destination = root / _MANIFEST
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(template, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"Unsafe manifest path: {value}")
    return path


def _verify_records(
    records: list[dict[str, Any]],
    contents: dict[str, bytes],
) -> None:
    expected = set(contents)
    declared: set[str] = set()
    for record in records:
        relative = _safe_relative(str(record["path"])).as_posix()
        if relative in declared:
            raise ValueError(f"Duplicate manifest path: {relative}")
        declared.add(relative)
        content = contents.get(relative)
        if content is None:
            raise ValueError(f"Manifest file is missing: {relative}")
        if int(record["size_bytes"]) != len(content):
            raise ValueError(f"Manifest size mismatch: {relative}")
        if str(record["sha256"]) != _sha256_bytes(content):
            raise ValueError(f"Manifest SHA-256 mismatch: {relative}")
    if declared != expected:
        missing = sorted(expected - declared)
        extra = sorted(declared - expected)
        raise ValueError(
            f"Manifest coverage mismatch: undeclared={missing}, absent={extra}"
        )


def verify_directory(root: Path) -> dict[str, Any]:
    manifest_path = root / _MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contents = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in _release_files(root)
    }
    _verify_records(list(manifest["files"]), contents)
    _verify_release_contract(manifest, contents)
    return manifest


def split_wheels(source: Path, common: Path, specific: Path) -> None:
    common.mkdir(parents=True, exist_ok=True)
    specific.mkdir(parents=True, exist_ok=True)
    wheels = sorted(source.glob("*.whl"))
    if not wheels:
        raise ValueError(f"No wheels downloaded into {source}")
    for wheel in wheels:
        destination_dir = common if wheel.name.endswith("-none-any.whl") else specific
        destination = destination_dir / wheel.name
        if destination.exists():
            if destination.read_bytes() != wheel.read_bytes():
                raise ValueError(f"Conflicting shared wheel: {wheel.name}")
            continue
        shutil.copy2(wheel, destination)


def _zip_info(relative: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(relative, _FIXED_TIME)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | mode) << 16
    return info


def create_zip(root: Path, destination: Path) -> None:
    verify_directory(root)
    temporary = destination.with_name(f".{destination.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    prefix = root.name
    with zipfile.ZipFile(
        temporary,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(
            (item for item in root.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(root).as_posix(),
        ):
            relative = f"{prefix}/{path.relative_to(root).as_posix()}"
            mode = path.stat().st_mode & 0o777
            archive.writestr(_zip_info(relative, mode), path.read_bytes())
    os.replace(temporary, destination)


def _verify_wheel_name(path: str) -> None:
    name = PurePosixPath(path).name.lower()
    if not name.endswith(".whl"):
        return
    if "arm64" in name or "aarch64" in name:
        raise ValueError(f"Unsupported architecture wheel: {path}")
    if "none-any.whl" in name:
        return
    if "x86_64" not in name and "universal2" not in name:
        raise ValueError(f"Wheel is not compatible with macOS x86_64: {path}")
    parts = PurePosixPath(path).parts
    minor_dir = next(
        (part for part in parts if part in {"py311", "py312", "py313", "py314"}),
        None,
    )
    if minor_dir is None:
        raise ValueError(f"Platform wheel is outside a Python wheelhouse: {path}")
    expected = f"cp{minor_dir[2:]}"
    if expected not in name and "-abi3-" not in name:
        raise ValueError(f"Wheel tag does not match {minor_dir}: {path}")


def _verify_release_contract(
    manifest: dict[str, Any],
    contents: dict[str, bytes],
) -> None:
    if manifest.get("format_version") != 1:
        raise ValueError("Unsupported release manifest format")
    if manifest.get("product") != "gigacode-agent-runtime":
        raise ValueError("Unexpected release product")
    if manifest.get("platform") != "macos":
        raise ValueError("Unexpected release platform")
    if manifest.get("minimum_macos_version") != "10.15":
        raise ValueError("Release requires macOS 10.15 or newer")
    if manifest.get("architectures") != ["x86_64"]:
        raise ValueError("Release architecture must be x86_64")
    if manifest.get("python_minors") != ["3.11", "3.12", "3.13", "3.14"]:
        raise ValueError("Release must cover Python 3.11 through 3.14")
    if manifest.get("release_stage") != "release-candidate":
        raise ValueError("Release manifest must identify a release candidate")

    required = {
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
        "corporate-profile/scenarios/corporate-skill-ref.yaml",
        "corporate-profile/scenarios/corporate-all-fields-example.yaml",
        "corporate-profile/scenarios/corporate-all-fields-agent-system.md",
        "corporate-profile/scenarios/corporate-all-fields-step-prompt.txt",
        "corporate-profile/scenarios/corporate-all-fields-output.schema",
        "corporate-profile/optional-scenarios/corporate-simple-skills.yaml",
        "corporate-profile/agents/business-analyst-proactive.md",
        "corporate-profile/agents/runtime-all-fields-example.md",
        "corporate-profile/skills/runtime-skill-probe/SKILL.md",
        "corporate-profile/skills/runtime-all-fields-example/SKILL.md",
        "examples/config-all-fields.yaml",
        "corporate-profile/commands/open_studio.md",
        "docs/corporate-acceptance-checklist.md",
        "docs/release-checklist.md",
        "requirements/runtime-py311.lock",
        "requirements/runtime-py312.lock",
        "requirements/runtime-py313.lock",
        "requirements/runtime-py314.lock",
    }
    absent = sorted(required - set(contents))
    if absent:
        raise ValueError(f"Required release files are missing: {absent}")
    if any(path.endswith((".tar.gz", ".tar.bz2", ".tgz")) for path in contents):
        raise ValueError("Source distributions are not allowed in offline release")
    wheel_paths = [path for path in contents if path.endswith(".whl")]
    if not any("gigacode_agent_runtime-" in path for path in wheel_paths):
        raise ValueError("Project wheel is missing")
    for minor in ("311", "312", "313", "314"):
        if not any(f"wheelhouse/py{minor}/" in path for path in wheel_paths):
            raise ValueError(f"Wheelhouse py{minor} is empty")
    for path in wheel_paths:
        _verify_wheel_name(path)


def verify_zip(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not members:
            raise ValueError("Release ZIP is empty")
        roots = {PurePosixPath(member.filename).parts[0] for member in members}
        if len(roots) != 1:
            raise ValueError("Release ZIP must contain exactly one root directory")
        root = next(iter(roots))
        contents: dict[str, bytes] = {}
        manifest: dict[str, Any] | None = None
        for member in members:
            parts = PurePosixPath(member.filename).parts
            if not parts or parts[0] != root or ".." in parts:
                raise ValueError(f"Unsafe ZIP member: {member.filename}")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"Symlink is not allowed in release ZIP: {member.filename}")
            if member.is_dir():
                continue
            relative = PurePosixPath(*parts[1:]).as_posix()
            content = archive.read(member)
            if relative == _MANIFEST:
                manifest = json.loads(content)
            else:
                contents[relative] = content
        if manifest is None:
            raise ValueError("Release manifest is missing")
        _verify_records(list(manifest["files"]), contents)
        _verify_release_contract(manifest, contents)
        return manifest


def write_checksum(path: Path) -> Path:
    destination = path.with_name(f"{path.name}.sha256")
    digest = _sha256_bytes(path.read_bytes())
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("root", type=Path)
    manifest.add_argument("template", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("root", type=Path)
    split = subparsers.add_parser("split-wheels")
    split.add_argument("source", type=Path)
    split.add_argument("common", type=Path)
    split.add_argument("specific", type=Path)
    package = subparsers.add_parser("package")
    package.add_argument("root", type=Path)
    package.add_argument("destination", type=Path)
    verify_archive = subparsers.add_parser("verify-zip")
    verify_archive.add_argument("archive", type=Path)
    checksum = subparsers.add_parser("checksum")
    checksum.add_argument("archive", type=Path)
    arguments = parser.parse_args()

    try:
        if arguments.command == "manifest":
            create_manifest(arguments.root, arguments.template)
        elif arguments.command == "verify":
            verify_directory(arguments.root)
        elif arguments.command == "split-wheels":
            split_wheels(arguments.source, arguments.common, arguments.specific)
        elif arguments.command == "package":
            create_zip(arguments.root, arguments.destination)
        elif arguments.command == "verify-zip":
            verify_zip(arguments.archive)
        elif arguments.command == "checksum":
            print(write_checksum(arguments.archive))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        print(f"release verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
