"""Discover and parse reusable user-level GigaCode agent profiles."""

from __future__ import annotations

import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import yaml

from .errors import AgentRuntimeError, ErrorCode
from .yaml_loader import RuntimeSafeLoader, safe_load

_AGENT_REFERENCE_PREFIX = "gigacode:"
_AGENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_AGENT_BYTES = 2 * 1024 * 1024
_APPROVAL_MODES = {"default", "plan", "auto-edit", "yolo", "bubble"}


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """A validated and immutable snapshot of one native GigaCode agent file."""

    name: str
    description: str
    system_prompt: str
    source_path: Path
    raw_content: str
    model: str | None = None
    approval_mode: str | None = None
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    color: str | None = None

    @property
    def reference(self) -> str:
        return f"{_AGENT_REFERENCE_PREFIX}{self.name}"


def agent_name_from_reference(reference: str) -> str:
    if not reference.startswith(_AGENT_REFERENCE_PREFIX):
        raise AgentRuntimeError(
            ErrorCode.AGENT_PROFILE_INVALID,
            "Agent reference must use the gigacode:<name> format",
            details={"agent_ref": reference},
        )
    name = reference[len(_AGENT_REFERENCE_PREFIX) :]
    if not _AGENT_NAME.fullmatch(name):
        raise AgentRuntimeError(
            ErrorCode.AGENT_PROFILE_INVALID,
            f"Invalid GigaCode agent name in reference: {reference}",
            details={"agent_ref": reference},
        )
    return name


def _invalid(path: Path, message: str, *, field: str | None = None) -> AgentRuntimeError:
    details: dict[str, object] = {"path": str(path)}
    if field is not None:
        details["field"] = field
    return AgentRuntimeError(
        ErrorCode.AGENT_PROFILE_INVALID,
        message,
        details=details,
    )


def _front_matter(text: str, path: Path) -> tuple[Mapping[str, Any], str]:
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        raise _invalid(path, "GigaCode agent must start with YAML front matter")
    try:
        closing = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise _invalid(path, "GigaCode agent YAML front matter is not closed") from exc
    header_text = "\n".join(lines[1:closing])
    try:
        for event in yaml.parse(header_text, Loader=RuntimeSafeLoader):
            if isinstance(event, yaml.events.AliasEvent):
                raise _invalid(path, "YAML aliases are not supported in GigaCode agents")
        loaded = safe_load(header_text)
    except AgentRuntimeError:
        raise
    except yaml.YAMLError as exc:
        raise _invalid(path, "Invalid GigaCode agent YAML front matter") from exc
    if not isinstance(loaded, Mapping):
        raise _invalid(path, "GigaCode agent front matter must be an object")
    system_prompt = "\n".join(lines[closing + 1 :]).strip()
    if not system_prompt:
        raise _invalid(path, "GigaCode agent system prompt is empty")
    return cast(Mapping[str, Any], loaded), system_prompt


def _required_string(metadata: Mapping[str, Any], path: Path, field: str) -> str:
    value = metadata.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _invalid(
            path,
            f"GigaCode agent field '{field}' must be a non-empty string",
            field=field,
        )
    return value.strip()


def _optional_string(
    metadata: Mapping[str, Any],
    path: Path,
    field: str,
) -> str | None:
    value = metadata.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _invalid(
            path,
            f"GigaCode agent field '{field}' must be a non-empty string",
            field=field,
        )
    return value.strip()


def _tool_list(metadata: Mapping[str, Any], path: Path, field: str) -> tuple[str, ...]:
    value = metadata.get(field)
    if value is None:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise _invalid(path, f"GigaCode agent field '{field}' must be a string list", field=field)
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        raise _invalid(path, f"GigaCode agent field '{field}' contains duplicates", field=field)
    return normalized


def load_agent_profile(path: Path, *, expected_root: Path | None = None) -> AgentProfile:
    """Load a native Markdown agent without allowing symlink/path escapes."""

    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AgentRuntimeError(
            ErrorCode.AGENT_PROFILE_NOT_FOUND,
            f"GigaCode agent file does not exist: {path}",
            details={"path": str(path)},
        ) from exc
    root = (expected_root or resolved.parent).resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise AgentRuntimeError(
            ErrorCode.PATH_NOT_ALLOWED,
            "GigaCode agent path escapes its catalog root",
            details={"path": str(resolved), "root": str(root)},
        )
    try:
        mode = path.lstat().st_mode
        size = resolved.stat().st_size
    except OSError as exc:
        raise _invalid(resolved, "Cannot inspect GigaCode agent file") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise AgentRuntimeError(
            ErrorCode.PATH_NOT_ALLOWED,
            "GigaCode agent must be a regular non-symlink file",
            details={"path": str(path)},
        )
    if size > _MAX_AGENT_BYTES:
        raise _invalid(
            resolved,
            f"GigaCode agent exceeds {_MAX_AGENT_BYTES} bytes",
        )
    try:
        content = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise _invalid(resolved, "Cannot read GigaCode agent as UTF-8") from exc
    metadata, system_prompt = _front_matter(content, resolved)
    name = _required_string(metadata, resolved, "name")
    if not _AGENT_NAME.fullmatch(name):
        raise _invalid(resolved, f"Invalid GigaCode agent name: {name}", field="name")
    description = _required_string(metadata, resolved, "description")
    approval_mode = _optional_string(metadata, resolved, "approvalMode")
    if approval_mode is not None and approval_mode not in _APPROVAL_MODES:
        raise _invalid(
            resolved,
            f"Unsupported GigaCode approvalMode: {approval_mode}",
            field="approvalMode",
        )
    return AgentProfile(
        name=name,
        description=description,
        system_prompt=system_prompt,
        source_path=resolved,
        raw_content=content,
        model=_optional_string(metadata, resolved, "model"),
        approval_mode=approval_mode,
        tools=_tool_list(metadata, resolved, "tools"),
        disallowed_tools=_tool_list(metadata, resolved, "disallowedTools"),
        color=_optional_string(metadata, resolved, "color"),
    )


class AgentProfileCatalog:
    """Name-indexed catalog rooted at ``~/.gigacode/agents``."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=False)

    def discover(self) -> Mapping[str, AgentProfile]:
        if not self.root.exists():
            return MappingProxyType({})
        if not self.root.is_dir() or self.root.is_symlink():
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                "GigaCode agent catalog must be a non-symlink directory",
                details={"path": str(self.root)},
            )
        profiles: dict[str, AgentProfile] = {}
        for path in sorted(self.root.glob("*.md")):
            profile = load_agent_profile(path, expected_root=self.root)
            if profile.name in profiles:
                raise AgentRuntimeError(
                    ErrorCode.AGENT_PROFILE_INVALID,
                    f"Duplicate GigaCode agent name: {profile.name}",
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

    def load(self, name_or_reference: str) -> AgentProfile:
        name = (
            agent_name_from_reference(name_or_reference)
            if name_or_reference.startswith(_AGENT_REFERENCE_PREFIX)
            else name_or_reference
        )
        if not _AGENT_NAME.fullmatch(name):
            raise AgentRuntimeError(
                ErrorCode.AGENT_PROFILE_INVALID,
                f"Invalid GigaCode agent name: {name}",
                details={"name": name},
            )
        profile = self.discover().get(name)
        if profile is None:
            raise AgentRuntimeError(
                ErrorCode.AGENT_PROFILE_NOT_FOUND,
                f"GigaCode agent profile was not found: {name}",
                details={"name": name, "root": str(self.root)},
            )
        return profile
