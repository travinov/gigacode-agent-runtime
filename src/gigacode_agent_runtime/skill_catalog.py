"""Discover and parse reusable user-level GigaCode Skills."""

from __future__ import annotations

import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import yaml

from .errors import AgentRuntimeError, ErrorCode
from .yaml_loader import RuntimeSafeLoader, safe_load

_SKILL_REFERENCE_PREFIX = "gigacode:"
_SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_SKILL_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SkillProfile:
    """A validated and immutable snapshot of one native GigaCode ``SKILL.md``."""

    name: str
    description: str
    instructions: str
    source_path: Path
    base_dir: Path
    raw_content: str
    priority: float | None = None
    user_invocable: bool | None = None
    disable_model_invocation: bool = False
    paths: tuple[str, ...] = ()

    @property
    def reference(self) -> str:
        return f"{_SKILL_REFERENCE_PREFIX}{self.name}"


def skill_name_from_reference(reference: str) -> str:
    if not reference.startswith(_SKILL_REFERENCE_PREFIX):
        raise AgentRuntimeError(
            ErrorCode.SKILL_PROFILE_INVALID,
            "Skill reference must use the gigacode:<name> format",
            details={"skill_ref": reference},
        )
    name = reference[len(_SKILL_REFERENCE_PREFIX) :]
    if not _SKILL_NAME.fullmatch(name):
        raise AgentRuntimeError(
            ErrorCode.SKILL_PROFILE_INVALID,
            f"Invalid GigaCode Skill name in reference: {reference}",
            details={"skill_ref": reference},
        )
    return name


def _invalid(path: Path, message: str, *, field: str | None = None) -> AgentRuntimeError:
    details: dict[str, object] = {"path": str(path)}
    if field is not None:
        details["field"] = field
    return AgentRuntimeError(
        ErrorCode.SKILL_PROFILE_INVALID,
        message,
        details=details,
    )


def _front_matter(text: str, path: Path) -> tuple[Mapping[str, Any], str]:
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        raise _invalid(path, "GigaCode Skill must start with YAML front matter")
    try:
        closing = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise _invalid(path, "GigaCode Skill YAML front matter is not closed") from exc
    header_text = "\n".join(lines[1:closing])
    try:
        for event in yaml.parse(header_text, Loader=RuntimeSafeLoader):
            if isinstance(event, yaml.events.AliasEvent):
                raise _invalid(path, "YAML aliases are not supported in GigaCode Skills")
        loaded = safe_load(header_text)
    except AgentRuntimeError:
        raise
    except yaml.YAMLError as exc:
        raise _invalid(path, "Invalid GigaCode Skill YAML front matter") from exc
    if not isinstance(loaded, Mapping):
        raise _invalid(path, "GigaCode Skill front matter must be an object")
    instructions = "\n".join(lines[closing + 1 :]).strip()
    if not instructions:
        raise _invalid(path, "GigaCode Skill instructions are empty")
    return cast(Mapping[str, Any], loaded), instructions


def _required_string(metadata: Mapping[str, Any], path: Path, field: str) -> str:
    value = metadata.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _invalid(
            path,
            f"GigaCode Skill field '{field}' must be a non-empty string",
            field=field,
        )
    return value.strip()


def _optional_bool(
    metadata: Mapping[str, Any],
    path: Path,
    field: str,
) -> bool | None:
    value = metadata.get(field)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise _invalid(path, f"GigaCode Skill field '{field}' must be boolean", field=field)
    return value


def _path_list(metadata: Mapping[str, Any], path: Path) -> tuple[str, ...]:
    value = metadata.get("paths")
    if value is None:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise _invalid(path, "GigaCode Skill field 'paths' must be a string list", field="paths")
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        raise _invalid(path, "GigaCode Skill field 'paths' contains duplicates", field="paths")
    return normalized


def load_skill_profile(path: Path, *, expected_root: Path | None = None) -> SkillProfile:
    """Load one Skill without allowing symlink or catalog-root escapes."""

    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AgentRuntimeError(
            ErrorCode.SKILL_PROFILE_NOT_FOUND,
            f"GigaCode Skill file does not exist: {path}",
            details={"path": str(path)},
        ) from exc
    root = (expected_root or resolved.parent.parent).resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise AgentRuntimeError(
            ErrorCode.PATH_NOT_ALLOWED,
            "GigaCode Skill path escapes its catalog root",
            details={"path": str(resolved), "root": str(root)},
        )
    try:
        directory_mode = path.parent.lstat().st_mode
        file_mode = path.lstat().st_mode
        size = resolved.stat().st_size
    except OSError as exc:
        raise _invalid(resolved, "Cannot inspect GigaCode Skill file") from exc
    if stat.S_ISLNK(directory_mode) or not stat.S_ISDIR(directory_mode):
        raise AgentRuntimeError(
            ErrorCode.PATH_NOT_ALLOWED,
            "GigaCode Skill directory must be a regular non-symlink directory",
            details={"path": str(path.parent)},
        )
    if stat.S_ISLNK(file_mode) or not stat.S_ISREG(file_mode):
        raise AgentRuntimeError(
            ErrorCode.PATH_NOT_ALLOWED,
            "GigaCode Skill must be a regular non-symlink file",
            details={"path": str(path)},
        )
    if size > _MAX_SKILL_BYTES:
        raise _invalid(resolved, f"GigaCode Skill exceeds {_MAX_SKILL_BYTES} bytes")
    try:
        content = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise _invalid(resolved, "Cannot read GigaCode Skill as UTF-8") from exc
    metadata, instructions = _front_matter(content, resolved)
    name = _required_string(metadata, resolved, "name")
    if not _SKILL_NAME.fullmatch(name):
        raise _invalid(resolved, f"Invalid GigaCode Skill name: {name}", field="name")
    description = _required_string(metadata, resolved, "description")
    priority_raw = metadata.get("priority")
    if priority_raw is not None and (
        not isinstance(priority_raw, (int, float)) or isinstance(priority_raw, bool)
    ):
        raise _invalid(
            resolved,
            "GigaCode Skill field 'priority' must be a number",
            field="priority",
        )
    if priority_raw is not None and not isfinite(float(priority_raw)):
        raise _invalid(
            resolved,
            "GigaCode Skill field 'priority' must be finite",
            field="priority",
        )
    disabled = _optional_bool(metadata, resolved, "disable-model-invocation")
    return SkillProfile(
        name=name,
        description=description,
        instructions=instructions,
        source_path=resolved,
        base_dir=resolved.parent,
        raw_content=content,
        priority=float(priority_raw) if priority_raw is not None else None,
        user_invocable=_optional_bool(metadata, resolved, "user-invocable"),
        disable_model_invocation=bool(disabled),
        paths=_path_list(metadata, resolved),
    )


class SkillProfileCatalog:
    """Name-indexed catalog rooted at ``~/.gigacode/skills``."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=False)

    def discover(self) -> Mapping[str, SkillProfile]:
        if not self.root.exists():
            return MappingProxyType({})
        if not self.root.is_dir() or self.root.is_symlink():
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                "GigaCode Skill catalog must be a non-symlink directory",
                details={"path": str(self.root)},
            )
        profiles: dict[str, SkillProfile] = {}
        for path in sorted(self.root.glob("*/SKILL.md")):
            profile = load_skill_profile(path, expected_root=self.root)
            if profile.name in profiles:
                raise AgentRuntimeError(
                    ErrorCode.SKILL_PROFILE_INVALID,
                    f"Duplicate GigaCode Skill name: {profile.name}",
                    details={
                        "name": profile.name,
                        "paths": [
                            str(profiles[profile.name].source_path),
                            str(profile.source_path),
                        ],
                    },
                )
            profiles[profile.name] = profile
        return MappingProxyType(profiles)

    def load(self, name_or_reference: str) -> SkillProfile:
        name = (
            skill_name_from_reference(name_or_reference)
            if name_or_reference.startswith(_SKILL_REFERENCE_PREFIX)
            else name_or_reference
        )
        if not _SKILL_NAME.fullmatch(name):
            raise AgentRuntimeError(
                ErrorCode.SKILL_PROFILE_INVALID,
                f"Invalid GigaCode Skill name: {name}",
                details={"name": name},
            )
        profile = self.discover().get(name)
        if profile is None:
            raise AgentRuntimeError(
                ErrorCode.SKILL_PROFILE_NOT_FOUND,
                f"GigaCode Skill was not found: {name}",
                details={"name": name, "root": str(self.root)},
            )
        return profile
