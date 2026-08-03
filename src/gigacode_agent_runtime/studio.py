"""Catalog-backed, transactional configuration service for local Studio."""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import secrets
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from .agent_catalog import AgentProfile, load_agent_profile
from .catalog import (
    builtin_scenarios_dir,
    create_agent_profile_catalog,
    create_skill_profile_catalog,
)
from .config import EffectiveConfig, load_config
from .domain import PermissionMode
from .errors import AgentRuntimeError, ErrorCode
from .hashing import canonical_json
from .locking import FileLock
from .plan_compiler import compile_plan, execution_plan_to_document
from .scenario_loader import LoadedScenario, ScenarioCatalog, load_scenario_file
from .serialization import atomic_write_text
from .skill_catalog import SkillProfile, load_skill_profile

_SCENARIO_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RESOURCE_KINDS = {"config", "scenario", "agent", "skill"}
_SCENARIO_SCOPES = {"user", "project"}
_MAX_DRAFT_BYTES = 2 * 1024 * 1024
_MAX_DIFF_BYTES = 256 * 1024
_MAX_PREVIEWS = 64
_PREVIEW_TTL_SECONDS = 10 * 60


def _raw_sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _path_hash(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()


def _read_target(path: Path) -> tuple[bytes | None, str | None]:
    if not path.exists():
        return None, None
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise AgentRuntimeError(
            ErrorCode.PATH_NOT_ALLOWED,
            f"Cannot read Studio target: {path}",
            details={"path": str(path)},
        ) from exc
    return content, _raw_sha256(content)


def _yaml_document(document: Mapping[str, Any]) -> str:
    return yaml.safe_dump(
        dict(document),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def _front_matter(metadata: Mapping[str, Any], body: str) -> str:
    header = yaml.safe_dump(
        dict(metadata),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()
    return f"---\n{header}\n---\n\n{body.strip()}\n"


def _string_list(
    document: Mapping[str, Any],
    field: str,
    *,
    resource: str,
) -> list[str]:
    raw = document.get(field, [])
    if not isinstance(raw, list) or any(
        not isinstance(item, str) or not item.strip() for item in raw
    ):
        raise AgentRuntimeError(
            ErrorCode.CONFIG_INVALID,
            f"Studio {resource} field '{field}' must be a string list",
            details={"field": field},
        )
    normalized = [item.strip() for item in raw]
    if len(normalized) != len(set(normalized)):
        raise AgentRuntimeError(
            ErrorCode.CONFIG_INVALID,
            f"Studio {resource} field '{field}' contains duplicates",
            details={"field": field},
        )
    return normalized


@dataclass(frozen=True, slots=True)
class StudioDraft:
    kind: str
    scope: str
    name: str | None
    document: dict[str, Any]

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> StudioDraft:
        unknown = set(payload) - {"kind", "scope", "name", "document"}
        if unknown:
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                "Studio draft contains unsupported fields",
                details={"fields": sorted(unknown)},
            )
        kind = payload.get("kind")
        scope = payload.get("scope")
        name = payload.get("name")
        document = payload.get("document")
        if not isinstance(kind, str) or kind not in _RESOURCE_KINDS:
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                "Studio draft kind is invalid",
                details={"kind": kind if isinstance(kind, str) else None},
            )
        if not isinstance(scope, str):
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                "Studio draft scope is required",
            )
        if name is not None and not isinstance(name, str):
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                "Studio draft name must be a string",
            )
        if not isinstance(document, dict):
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                "Studio draft document must be an object",
            )
        encoded = canonical_json(document).encode("utf-8")
        if len(encoded) > _MAX_DRAFT_BYTES:
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                f"Studio draft exceeds {_MAX_DRAFT_BYTES} bytes",
                details={"size": len(encoded)},
            )
        return cls(
            kind=kind,
            scope=scope,
            name=name.strip() if isinstance(name, str) else None,
            document=cast(dict[str, Any], document),
        )


@dataclass(frozen=True, slots=True)
class ManagedCandidate:
    draft: StudioDraft
    target: Path
    root: Path
    content: str
    validation: Mapping[str, object]
    activation: str
    override: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class PreviewRecord:
    preview_id: str
    session_digest: str
    candidate: ManagedCandidate
    observed_hash: str | None
    candidate_hash: str
    created_at: float
    expires_at: float


def _agent_document(profile: AgentProfile) -> dict[str, Any]:
    document: dict[str, Any] = {
        "name": profile.name,
        "description": profile.description,
        "system_prompt": profile.system_prompt,
        "tools": list(profile.tools),
        "disallowedTools": list(profile.disallowed_tools),
    }
    if profile.model is not None:
        document["model"] = profile.model
    if profile.approval_mode is not None:
        document["approvalMode"] = profile.approval_mode
    if profile.color is not None:
        document["color"] = profile.color
    return document


def _skill_document(profile: SkillProfile) -> dict[str, Any]:
    document: dict[str, Any] = {
        "name": profile.name,
        "description": profile.description,
        "instructions": profile.instructions,
        "paths": list(profile.paths),
    }
    if profile.priority is not None:
        document["priority"] = profile.priority
    if profile.user_invocable is not None:
        document["user-invocable"] = profile.user_invocable
    if profile.disable_model_invocation:
        document["disable-model-invocation"] = True
    return document


class StudioService:
    """Authoritative local configuration catalog and transaction boundary."""

    def __init__(
        self,
        config: EffectiveConfig,
        *,
        project_scenarios: Path | None = None,
        preview_ttl_seconds: int = _PREVIEW_TTL_SECONDS,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.project_scenarios = (
            project_scenarios.expanduser().absolute() if project_scenarios is not None else None
        )
        self.workspace = (
            self.project_scenarios.parent.parent
            if self.project_scenarios is not None
            else Path.cwd().resolve(strict=False)
        )
        self._agent_catalog = create_agent_profile_catalog(config)
        self._skill_catalog = create_skill_profile_catalog(config)
        self._preview_ttl_seconds = preview_ttl_seconds
        self._now = now
        self._previews: dict[str, PreviewRecord] = {}

    @staticmethod
    def _scenario_summary(scenario: LoadedScenario) -> dict[str, object]:
        metadata = cast(Mapping[str, Any], scenario.document["metadata"])
        return {
            "name": scenario.name,
            "title": str(metadata["title"]),
            "description": metadata.get("description"),
            "source_level": scenario.source.level,
            "source_path": str(scenario.source.path),
            "writable": scenario.source.level in _SCENARIO_SCOPES,
        }

    def _scenario_catalog_for(self, scope: str) -> ScenarioCatalog:
        if scope == "builtin":
            return ScenarioCatalog(
                builtin_dir=builtin_scenarios_dir(),
                workspace_root=self.workspace,
                agent_catalog=self._agent_catalog,
                skill_catalog=self._skill_catalog,
            )
        if scope == "user":
            return ScenarioCatalog(
                user_dir=self.config.paths.user_scenarios,
                workspace_root=self.workspace,
                agent_catalog=self._agent_catalog,
                skill_catalog=self._skill_catalog,
            )
        if scope == "project" and self.project_scenarios is not None:
            return ScenarioCatalog(
                project_dir=self.project_scenarios,
                workspace_root=self.workspace,
                agent_catalog=self._agent_catalog,
                skill_catalog=self._skill_catalog,
            )
        raise AgentRuntimeError(
            ErrorCode.PATH_NOT_ALLOWED,
            f"Studio scenario scope is not available: {scope}",
            details={"scope": scope},
        )

    def _scenario_entries(self) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        scopes = ["builtin", "user"]
        if self.project_scenarios is not None:
            scopes.append("project")
        for scope in scopes:
            catalog = self._scenario_catalog_for(scope)
            entries.extend(
                self._scenario_summary(entry.scenario)
                for entry in sorted(
                    catalog.discover().values(),
                    key=lambda item: item.name,
                )
            )
        return entries

    @staticmethod
    def _agent_summary(profile: AgentProfile) -> dict[str, object]:
        return {
            "name": profile.name,
            "agent_ref": profile.reference,
            "description": profile.description,
            "model": profile.model,
            "approval_mode": profile.approval_mode,
            "tools": list(profile.tools),
            "disallowed_tools": list(profile.disallowed_tools),
            "color": profile.color,
            "source_level": "user",
            "source_path": str(profile.source_path),
            "writable": True,
        }

    @staticmethod
    def _skill_summary(profile: SkillProfile) -> dict[str, object]:
        return {
            "name": profile.name,
            "skill_ref": profile.reference,
            "description": profile.description,
            "source_level": profile.source_level,
            "source_path": str(profile.source_path),
            "canonical_directory": profile.canonical_directory,
            "priority": profile.priority,
            "user_invocable": profile.user_invocable,
            "disable_model_invocation": profile.disable_model_invocation,
            "paths": list(profile.paths),
            "writable": profile.source_level == "user",
            "shadowed_sources": [
                {
                    "source_level": shadowed.source_level,
                    "source_path": str(shadowed.source_path),
                    "canonical_directory": shadowed.canonical_directory,
                }
                for shadowed in profile.shadowed_profiles
            ],
        }

    def catalog(self) -> dict[str, object]:
        agents = sorted(
            self._agent_catalog.discover().values(),
            key=lambda profile: profile.name,
        )
        skills = sorted(
            self._skill_catalog.discover().values(),
            key=lambda profile: profile.name,
        )
        known_tools = sorted(
            {tool for profile in agents for tool in (*profile.tools, *profile.disallowed_tools)}
        )
        return {
            "config": {
                "source_path": str(self.config.source_path),
                "document": self.config.to_snapshot(),
                "requires_reconnect": True,
            },
            "paths": {
                "home": str(self.config.paths.home),
                "data_dir": str(self.config.runtime.data_dir),
                "user_scenarios": str(self.config.paths.user_scenarios),
                "project_scenarios": (
                    str(self.project_scenarios) if self.project_scenarios is not None else None
                ),
                "agents": str(self._agent_catalog.root),
                "skills": str(self._skill_catalog.root),
                "skill_roots": {
                    level: str(root) for level, root in self._skill_catalog.roots.items()
                },
                "backups": str(self.config.runtime.data_dir / "studio-backups"),
            },
            "choices": {
                "permissions": [mode.value for mode in PermissionMode],
                "models": list(self.config.gigacode.model_allowlist),
                "approval_modes": ["default", "plan", "auto-edit", "yolo", "bubble"],
                "known_tools": known_tools,
                "scenario_scopes": (
                    ["user", "project"] if self.project_scenarios is not None else ["user"]
                ),
            },
            "scenarios": self._scenario_entries(),
            "agents": [self._agent_summary(profile) for profile in agents],
            "skills": [self._skill_summary(profile) for profile in skills],
            "skill_selection_policy": ("user > extension > bundled; canonical directory wins ties"),
        }

    def _skill_for_scope(self, scope: str, name: str) -> SkillProfile:
        active = self._skill_catalog.load(name)
        candidates = (active, *active.shadowed_profiles)
        for profile in candidates:
            if profile.source_level == scope:
                return profile
        raise AgentRuntimeError(
            ErrorCode.SKILL_PROFILE_NOT_FOUND,
            f"GigaCode Skill was not found in source {scope}: {name}",
            details={"name": name, "source_level": scope},
        )

    def detail(self, kind: str, scope: str, name: str | None = None) -> dict[str, object]:
        if kind == "config":
            if scope != "selected" or name is not None:
                raise AgentRuntimeError(
                    ErrorCode.CONFIG_INVALID,
                    "Studio config detail requires selected scope and no name",
                )
            return {
                "kind": kind,
                "scope": scope,
                "name": None,
                "source_path": str(self.config.source_path),
                "writable": True,
                "document": self.config.to_snapshot(),
            }
        if not isinstance(name, str) or not name:
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                f"Studio {kind} detail requires a name",
            )
        if kind == "scenario":
            scenario = self._scenario_catalog_for(scope).load(name)
            return {
                "kind": kind,
                "scope": scope,
                "name": name,
                "source_path": str(scenario.source.path),
                "writable": scope in _SCENARIO_SCOPES,
                "document": dict(scenario.document),
            }
        if kind == "agent":
            if scope != "user":
                raise AgentRuntimeError(
                    ErrorCode.PATH_NOT_ALLOWED,
                    "Only user GigaCode agents are managed by Studio",
                    details={"scope": scope},
                )
            agent_profile = self._agent_catalog.load(name)
            return {
                "kind": kind,
                "scope": scope,
                "name": name,
                "source_path": str(agent_profile.source_path),
                "writable": True,
                "document": _agent_document(agent_profile),
            }
        if kind == "skill":
            skill_profile = self._skill_for_scope(scope, name)
            return {
                "kind": kind,
                "scope": scope,
                "name": name,
                "source_path": str(skill_profile.source_path),
                "writable": scope == "user",
                "document": _skill_document(skill_profile),
                "shadowed_sources": [
                    self._skill_summary(shadowed) for shadowed in skill_profile.shadowed_profiles
                ],
            }
        raise AgentRuntimeError(
            ErrorCode.CONFIG_INVALID,
            f"Unsupported Studio resource kind: {kind}",
        )

    @staticmethod
    def _validate_name(kind: str, name: str | None) -> str:
        pattern = _SCENARIO_NAME if kind == "scenario" else _PROFILE_NAME
        if not isinstance(name, str) or not pattern.fullmatch(name):
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                f"Studio {kind} name is invalid: {name}",
                details={"kind": kind, "name": name},
            )
        return name

    def _managed_path(self, draft: StudioDraft) -> tuple[Path, Path]:
        if draft.kind == "config":
            if draft.scope != "selected" or draft.name is not None:
                raise AgentRuntimeError(
                    ErrorCode.CONFIG_INVALID,
                    "Studio config draft requires selected scope and no name",
                )
            return self.config.source_path.absolute(), self.config.source_path.parent.absolute()
        name = self._validate_name(draft.kind, draft.name)
        if draft.kind == "scenario":
            if draft.scope == "user":
                root = self.config.paths.user_scenarios.absolute()
            elif draft.scope == "project" and self.project_scenarios is not None:
                root = self.project_scenarios.absolute()
            else:
                raise AgentRuntimeError(
                    ErrorCode.PATH_NOT_ALLOWED,
                    f"Studio scenario scope is not writable: {draft.scope}",
                    details={"scope": draft.scope},
                )
            existing = self._existing_scenario_path(draft.scope, name)
            return (existing or (root / f"{name}.yaml")), root
        if draft.scope != "user":
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                f"Studio {draft.kind} scope is not writable: {draft.scope}",
                details={"scope": draft.scope},
            )
        if draft.kind == "agent":
            root = self._agent_catalog.root.absolute()
            return self._existing_agent_path(name) or (root / f"{name}.md"), root
        root = self._skill_catalog.root.absolute()
        return self._existing_skill_path(name) or (root / name / "SKILL.md"), root

    def _existing_scenario_path(self, scope: str, name: str) -> Path | None:
        try:
            return self._scenario_catalog_for(scope).load(name).source.path
        except AgentRuntimeError as error:
            if error.code is ErrorCode.SCENARIO_INVALID and "not found" in error.message:
                return None
            raise

    def _existing_agent_path(self, name: str) -> Path | None:
        try:
            return self._agent_catalog.load(name).source_path
        except AgentRuntimeError as error:
            if error.code is ErrorCode.AGENT_PROFILE_NOT_FOUND:
                return None
            raise

    def _existing_skill_path(self, name: str) -> Path | None:
        try:
            return self._skill_for_scope("user", name).source_path
        except AgentRuntimeError as error:
            if error.code is ErrorCode.SKILL_PROFILE_NOT_FOUND:
                return None
            raise

    @staticmethod
    def _assert_managed_target(target: Path, root: Path) -> None:
        target_absolute = target.expanduser().absolute()
        root_absolute = root.expanduser().absolute()
        if target_absolute != root_absolute and not target_absolute.is_relative_to(root_absolute):
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                "Studio target escapes its managed root",
                details={"path": str(target_absolute), "root": str(root_absolute)},
            )
        boundary = root_absolute.parent
        for candidate in (target_absolute, *target_absolute.parents):
            if candidate == boundary:
                break
            if candidate.is_symlink():
                raise AgentRuntimeError(
                    ErrorCode.PATH_NOT_ALLOWED,
                    "Studio refuses symbolic links in managed paths",
                    details={"path": str(candidate)},
                )
        if root_absolute.exists() and not root_absolute.is_dir():
            raise AgentRuntimeError(
                ErrorCode.PATH_NOT_ALLOWED,
                "Studio managed root is not a directory",
                details={"root": str(root_absolute)},
            )

    def _serialize(self, draft: StudioDraft) -> str:
        if draft.kind in {"config", "scenario"}:
            if draft.kind == "scenario":
                name = self._validate_name("scenario", draft.name)
                metadata = draft.document.get("metadata")
                if not isinstance(metadata, Mapping) or metadata.get("name") != name:
                    raise AgentRuntimeError(
                        ErrorCode.SCENARIO_INVALID,
                        "Scenario metadata.name must match the Studio resource name",
                        details={"name": name},
                    )
            return _yaml_document(draft.document)
        name = self._validate_name(draft.kind, draft.name)
        if draft.document.get("name") != name:
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                f"Studio {draft.kind} document name must match the resource name",
                details={"name": name},
            )
        if draft.kind == "agent":
            body = draft.document.get("system_prompt")
            if not isinstance(body, str) or not body.strip():
                raise AgentRuntimeError(
                    ErrorCode.AGENT_PROFILE_INVALID,
                    "Studio agent system_prompt must be non-empty",
                    details={"field": "system_prompt"},
                )
            agent_metadata: dict[str, Any] = {
                "name": name,
                "description": draft.document.get("description"),
            }
            for field in ("model", "approvalMode", "color"):
                value = draft.document.get(field)
                if value not in (None, ""):
                    agent_metadata[field] = value
            tools = _string_list(draft.document, "tools", resource="agent")
            disallowed = _string_list(
                draft.document,
                "disallowedTools",
                resource="agent",
            )
            if tools:
                agent_metadata["tools"] = tools
            if disallowed:
                agent_metadata["disallowedTools"] = disallowed
            return _front_matter(agent_metadata, body)
        instructions = draft.document.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            raise AgentRuntimeError(
                ErrorCode.SKILL_PROFILE_INVALID,
                "Studio Skill instructions must be non-empty",
                details={"field": "instructions"},
            )
        skill_metadata: dict[str, Any] = {
            "name": name,
            "description": draft.document.get("description"),
        }
        priority = draft.document.get("priority")
        if priority is not None:
            skill_metadata["priority"] = priority
        for field in ("user-invocable", "disable-model-invocation"):
            value = draft.document.get(field)
            if value is not None:
                skill_metadata[field] = value
        paths = _string_list(draft.document, "paths", resource="Skill")
        if paths:
            skill_metadata["paths"] = paths
        return _front_matter(skill_metadata, instructions)

    @staticmethod
    def _input_values(document: Mapping[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        raw_inputs = document.get("inputs", {})
        if not isinstance(raw_inputs, Mapping):
            return values
        fallback: dict[str, Any] = {
            "string": "studio-preview",
            "integer": 0,
            "number": 0,
            "boolean": False,
            "object": {},
            "array": [],
        }
        for name, raw in raw_inputs.items():
            if not isinstance(name, str) or not isinstance(raw, Mapping):
                continue
            if "default" in raw:
                values[name] = raw["default"]
            else:
                values[name] = fallback.get(str(raw.get("type")), "studio-preview")
        return values

    def _temporary_scenario_path(self, target: Path, content: str) -> Path:
        if target.parent.exists():
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{target.stem}.studio-preview.",
                suffix=".yaml",
                dir=target.parent,
            )
            path = Path(raw_path)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(content)
                return path
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        directory = Path(tempfile.mkdtemp(prefix="gar-studio-scenario-"))
        path = directory / f"{target.stem}.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    @staticmethod
    def _cleanup_temporary_path(path: Path, *, target_parent: Path) -> None:
        parent = path.parent
        path.unlink(missing_ok=True)
        if parent != target_parent and parent.name.startswith("gar-studio-scenario-"):
            with suppress(OSError):
                parent.rmdir()

    def _validate_scenario(self, target: Path, content: str) -> dict[str, object]:
        path = self._temporary_scenario_path(target, content)
        try:
            scenario = load_scenario_file(
                path,
                level="studio-preview",
                workspace_root=self.workspace,
                agent_catalog=self._agent_catalog,
                skill_catalog=self._skill_catalog,
            )
            plan = compile_plan(
                scenario,
                self.config,
                inputs=self._input_values(scenario.document),
                workspace=self.workspace,
            )
            plan_document = execution_plan_to_document(plan)
            return {
                "valid": True,
                "scenario": scenario.name,
                "waves": plan_document["waves"],
                "agent_refs": sorted(scenario.agent_profiles),
                "skill_refs": sorted(scenario.skill_profiles),
            }
        finally:
            self._cleanup_temporary_path(path, target_parent=target.parent)

    def _validate_candidate(self, candidate: ManagedCandidate) -> Mapping[str, object]:
        kind = candidate.draft.kind
        if kind == "config":
            with tempfile.TemporaryDirectory(prefix="gar-studio-config-") as raw:
                path = Path(raw) / "config.yaml"
                path.write_text(candidate.content, encoding="utf-8")
                effective = load_config(path, home=self.config.paths.home)
            return {
                "valid": True,
                "schema_version": effective.schema_version,
                "data_dir": str(effective.runtime.data_dir),
            }
        if kind == "scenario":
            return self._validate_scenario(candidate.target, candidate.content)
        if kind == "agent":
            with tempfile.TemporaryDirectory(prefix="gar-studio-agent-") as raw:
                root = Path(raw)
                path = root / f"{candidate.draft.name}.md"
                path.write_text(candidate.content, encoding="utf-8")
                candidate_agent = load_agent_profile(path, expected_root=root)
            return {
                "valid": True,
                "name": candidate_agent.name,
                "agent_ref": candidate_agent.reference,
            }
        with tempfile.TemporaryDirectory(prefix="gar-studio-skill-") as raw:
            root = Path(raw)
            path = root / str(candidate.draft.name) / "SKILL.md"
            path.parent.mkdir()
            path.write_text(candidate.content, encoding="utf-8")
            candidate_skill = load_skill_profile(path, expected_root=root)
        return {
            "valid": True,
            "name": candidate_skill.name,
            "skill_ref": candidate_skill.reference,
        }

    def _candidate(self, draft: StudioDraft) -> ManagedCandidate:
        target, root = self._managed_path(draft)
        self._assert_managed_target(target, root)
        content = self._serialize(draft)
        activation = (
            "Reconnect GigaCode/MCP to load the saved runtime configuration."
            if draft.kind == "config"
            else "Available to subsequent catalog discovery and new plans."
        )
        override: Mapping[str, object] | None = None
        if draft.kind == "skill":
            name = self._validate_name("skill", draft.name)
            try:
                active_skill = self._skill_catalog.load(name)
            except AgentRuntimeError as error:
                if error.code is not ErrorCode.SKILL_PROFILE_NOT_FOUND:
                    raise
            else:
                if active_skill.source_level != "user":
                    override = {
                        "will_override": True,
                        "source_level": active_skill.source_level,
                        "source_path": str(active_skill.source_path),
                    }
        provisional = ManagedCandidate(
            draft=draft,
            target=target,
            root=root,
            content=content,
            validation={},
            activation=activation,
            override=override,
        )
        validation = self._validate_candidate(provisional)
        return ManagedCandidate(
            draft=draft,
            target=target,
            root=root,
            content=content,
            validation=validation,
            activation=activation,
            override=override,
        )

    def _purge_previews(self) -> None:
        now = self._now()
        self._previews = {
            preview_id: preview
            for preview_id, preview in self._previews.items()
            if preview.expires_at > now
        }
        if len(self._previews) >= _MAX_PREVIEWS:
            oldest = min(
                self._previews.values(),
                key=lambda preview: preview.created_at,
            )
            self._previews.pop(oldest.preview_id, None)

    @staticmethod
    def _session_digest(session_token: str) -> str:
        return hashlib.sha256(session_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _diff(path: Path, before: bytes | None, after: str) -> str:
        before_text = before.decode("utf-8") if before is not None else ""
        lines = difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{path} (current)",
            tofile=f"{path} (candidate)",
        )
        diff = "".join(lines)
        encoded = diff.encode("utf-8")
        if len(encoded) <= _MAX_DIFF_BYTES:
            return diff
        marker = "\n... Studio diff truncated ...\n"
        truncated = encoded[: _MAX_DIFF_BYTES - len(marker.encode("utf-8"))]
        return truncated.decode("utf-8", errors="ignore") + marker

    def preview(
        self,
        payload: Mapping[str, Any],
        *,
        session_token: str,
    ) -> dict[str, object]:
        draft = StudioDraft.parse(payload)
        candidate = self._candidate(draft)
        before, observed_hash = _read_target(candidate.target)
        candidate_hash = _raw_sha256(candidate.content.encode("utf-8"))
        self._purge_previews()
        now = self._now()
        preview_id = secrets.token_urlsafe(32)
        self._previews[preview_id] = PreviewRecord(
            preview_id=preview_id,
            session_digest=self._session_digest(session_token),
            candidate=candidate,
            observed_hash=observed_hash,
            candidate_hash=candidate_hash,
            created_at=now,
            expires_at=now + self._preview_ttl_seconds,
        )
        return {
            "preview_id": preview_id,
            "kind": draft.kind,
            "scope": draft.scope,
            "name": draft.name,
            "target_path": str(candidate.target),
            "current_hash": observed_hash,
            "candidate_hash": candidate_hash,
            "expires_at": now + self._preview_ttl_seconds,
            "diff": self._diff(candidate.target, before, candidate.content),
            "validation": dict(candidate.validation),
            "activation": candidate.activation,
            "override": dict(candidate.override) if candidate.override is not None else None,
        }

    def _take_preview(self, preview_id: str, session_token: str) -> PreviewRecord:
        self._purge_previews()
        preview = self._previews.get(preview_id)
        if preview is None:
            raise AgentRuntimeError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "Studio preview is missing, expired, or already used",
            )
        if not secrets.compare_digest(
            preview.session_digest,
            self._session_digest(session_token),
        ):
            raise AgentRuntimeError(
                ErrorCode.PERMISSION_DENIED,
                "Studio preview belongs to another session",
            )
        self._previews.pop(preview_id, None)
        return preview

    def _backup(self, preview: PreviewRecord, before: bytes) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        directory = (
            self.config.runtime.data_dir
            / "studio-backups"
            / f"{timestamp}-{preview.preview_id[:8]}"
        )
        destination = directory / (
            f"{preview.candidate.draft.kind}-{_path_hash(preview.candidate.target)[:12]}-"
            f"{preview.candidate.target.name}"
        )
        atomic_write_text(destination, before.decode("utf-8"))
        os.chmod(destination, 0o600)
        return destination

    def _validate_persisted(self, candidate: ManagedCandidate) -> Mapping[str, object]:
        if candidate.draft.kind == "config":
            effective = load_config(candidate.target, home=self.config.paths.home)
            return {"valid": True, "schema_version": effective.schema_version}
        if candidate.draft.kind == "scenario":
            scenario = load_scenario_file(
                candidate.target,
                level=candidate.draft.scope,
                workspace_root=self.workspace,
                agent_catalog=self._agent_catalog,
                skill_catalog=self._skill_catalog,
            )
            plan = compile_plan(
                scenario,
                self.config,
                inputs=self._input_values(scenario.document),
                workspace=self.workspace,
            )
            return {
                "valid": True,
                "scenario": scenario.name,
                "waves": execution_plan_to_document(plan)["waves"],
            }
        if candidate.draft.kind == "agent":
            persisted_agent = load_agent_profile(
                candidate.target,
                expected_root=self._agent_catalog.root,
            )
            return {"valid": True, "name": persisted_agent.name}
        persisted_skill = load_skill_profile(
            candidate.target,
            expected_root=self._skill_catalog.root,
        )
        return {"valid": True, "name": persisted_skill.name}

    def apply(self, preview_id: str, *, session_token: str) -> dict[str, object]:
        if not isinstance(preview_id, str) or not preview_id:
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                "Studio preview_id is required",
            )
        preview = self._take_preview(preview_id, session_token)
        candidate = preview.candidate
        self._assert_managed_target(candidate.target, candidate.root)
        lock_path = (
            self.config.runtime.data_dir
            / ".studio"
            / "locks"
            / f"{_path_hash(candidate.target)}.lock"
        )
        backup: Path | None = None
        with FileLock(lock_path):
            before, current_hash = _read_target(candidate.target)
            if current_hash != preview.observed_hash:
                raise AgentRuntimeError(
                    ErrorCode.PLAN_CONFLICT,
                    "Studio target changed after preview",
                    details={
                        "path": str(candidate.target),
                        "preview_hash": preview.observed_hash,
                        "current_hash": current_hash,
                    },
                    retryable=True,
                )
            if before is not None:
                try:
                    before.decode("utf-8")
                except UnicodeError as exc:
                    raise AgentRuntimeError(
                        ErrorCode.PATH_NOT_ALLOWED,
                        "Studio target is not valid UTF-8",
                        details={"path": str(candidate.target)},
                    ) from exc
                backup = self._backup(preview, before)
            try:
                atomic_write_text(candidate.target, candidate.content)
                os.chmod(candidate.target, 0o600)
                persisted_validation = self._validate_persisted(candidate)
            except BaseException as error:
                try:
                    if before is None:
                        candidate.target.unlink(missing_ok=True)
                    else:
                        atomic_write_text(candidate.target, before.decode("utf-8"))
                        os.chmod(candidate.target, 0o600)
                except OSError as rollback_error:
                    raise AgentRuntimeError(
                        ErrorCode.INTERNAL_ERROR,
                        "Studio write failed and rollback could not restore the target",
                        details={
                            "path": str(candidate.target),
                            "backup_path": str(backup) if backup is not None else None,
                            "rollback_error": type(rollback_error).__name__,
                        },
                    ) from error
                raise
        return {
            "applied": True,
            "kind": candidate.draft.kind,
            "scope": candidate.draft.scope,
            "name": candidate.draft.name,
            "target_path": str(candidate.target),
            "candidate_hash": preview.candidate_hash,
            "backup_path": str(backup) if backup is not None else None,
            "validation": dict(persisted_validation),
            "activation": candidate.activation,
        }
