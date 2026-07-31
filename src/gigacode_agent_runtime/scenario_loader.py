"""Discover, validate, and snapshot declarative scenarios."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import yaml

from .agent_catalog import AgentProfile, AgentProfileCatalog
from .domain import ScenarioSource
from .errors import AgentRuntimeError, ErrorCode
from .interpolation import validate_template
from .schema_registry import validate_document
from .source_resolver import ContainedSourceResolver, ResolvedResource
from .yaml_loader import RuntimeSafeLoader, safe_load

_SCENARIO_SUFFIXES = {".yaml", ".yml", ".json"}
_MAX_SCENARIO_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class LoadedScenario:
    name: str
    document: Mapping[str, Any]
    source: ScenarioSource
    resources: Mapping[str, ResolvedResource]
    agent_profiles: Mapping[str, AgentProfile]


@dataclass(frozen=True, slots=True)
class ScenarioCatalogEntry:
    name: str
    title: str
    source: ScenarioSource
    scenario: LoadedScenario


def _load_yaml_without_aliases(text: str, path: Path) -> object:
    try:
        for event in yaml.parse(text, Loader=RuntimeSafeLoader):
            if isinstance(event, yaml.events.AliasEvent):
                raise AgentRuntimeError(
                    ErrorCode.SCENARIO_INVALID,
                    "YAML aliases are not supported in scenarios",
                    details={"path": str(path)},
                )
        return safe_load(text)
    except AgentRuntimeError:
        raise
    except yaml.YAMLError as exc:
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            f"Invalid scenario YAML: {path}",
            details={"path": str(path)},
        ) from exc


def _read_scenario_document(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
        if size > _MAX_SCENARIO_BYTES:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Scenario exceeds {_MAX_SCENARIO_BYTES} bytes: {path}",
                details={"path": str(path), "size": size},
            )
        text = path.read_text(encoding="utf-8")
        loaded = json.loads(text) if path.suffix.lower() == ".json" else _load_yaml_without_aliases(
            text, path
        )
    except AgentRuntimeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            f"Cannot read scenario: {path}",
            details={"path": str(path)},
        ) from exc
    if not isinstance(loaded, dict):
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            "Scenario document must be an object",
            details={"path": "/"},
        )
    return cast(dict[str, Any], loaded)


def _validate_interpolation_values(value: object) -> None:
    if isinstance(value, str):
        validate_template(value)
    elif isinstance(value, Mapping):
        for nested in value.values():
            _validate_interpolation_values(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_interpolation_values(nested)


def _iter_agent_steps(document: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    steps = cast(Mapping[str, Any], document["steps"])
    for raw_step in steps.values():
        step = cast(Mapping[str, Any], raw_step)
        if step["kind"] == "agent":
            yield step
            continue
        body = cast(Mapping[str, Any], step["body"])
        body_steps = cast(Mapping[str, Any], body["steps"])
        for raw_body_step in body_steps.values():
            yield cast(Mapping[str, Any], raw_body_step)


def _validate_interpolations(document: Mapping[str, Any]) -> None:
    result = cast(Mapping[str, Any], document["result"])
    _validate_interpolation_values(result["from"])
    for step in _iter_agent_steps(document):
        prompt = cast(Mapping[str, Any], step["prompt"])
        if "template" in prompt:
            _validate_interpolation_values(prompt["template"])
        if "context" in prompt:
            _validate_interpolation_values(prompt["context"])
        if "when" in step:
            _validate_interpolation_values(step["when"])

    for raw_step in cast(Mapping[str, Any], document["steps"]).values():
        step = cast(Mapping[str, Any], raw_step)
        if step["kind"] == "loop":
            _validate_interpolation_values(step["until"])
            if "no_progress" in step:
                _validate_interpolation_values(step["no_progress"])


def _snapshot_resources(
    document: Mapping[str, Any],
    resolver: ContainedSourceResolver,
    base_dir: Path,
    agent_catalog: AgentProfileCatalog | None,
) -> tuple[Mapping[str, ResolvedResource], Mapping[str, AgentProfile]]:
    resources: dict[str, ResolvedResource] = {}
    agent_profiles: dict[str, AgentProfile] = {}
    for raw_agent in cast(Mapping[str, Any], document["agents"]).values():
        agent = cast(Mapping[str, Any], raw_agent)
        reference = agent.get("system_prompt_file")
        if isinstance(reference, str):
            resources[reference] = resolver.read_text(reference, base_dir=base_dir)
        agent_ref = agent.get("agent_ref")
        if isinstance(agent_ref, str):
            if agent_catalog is None:
                raise AgentRuntimeError(
                    ErrorCode.AGENT_PROFILE_NOT_FOUND,
                    "Scenario uses agent_ref but no GigaCode agent catalog is configured",
                    details={"agent_ref": agent_ref},
                )
            profile = agent_catalog.load(agent_ref)
            agent_profiles[agent_ref] = profile
            resources[agent_ref] = ResolvedResource(
                reference=agent_ref,
                path=profile.source_path,
                content=profile.raw_content,
            )

    for step in _iter_agent_steps(document):
        prompt = cast(Mapping[str, Any], step["prompt"])
        template_file = prompt.get("template_file")
        if isinstance(template_file, str):
            resources[template_file] = resolver.read_text(template_file, base_dir=base_dir)
        output_schema = step["output_schema"]
        if isinstance(output_schema, str):
            resource = resolver.read_text(output_schema, base_dir=base_dir)
            try:
                parsed = json.loads(resource.content)
            except json.JSONDecodeError as exc:
                raise AgentRuntimeError(
                    ErrorCode.SCENARIO_INVALID,
                    f"Output schema is not valid JSON: {output_schema}",
                    details={"reference": output_schema},
                ) from exc
            if not isinstance(parsed, dict):
                raise AgentRuntimeError(
                    ErrorCode.SCENARIO_INVALID,
                    f"Output schema must be a JSON object: {output_schema}",
                    details={"reference": output_schema},
                )
            resources[output_schema] = resource
    return MappingProxyType(resources), MappingProxyType(agent_profiles)


def load_scenario_file(
    path: Path,
    *,
    level: str = "direct",
    workspace_root: Path | None = None,
    agent_catalog: AgentProfileCatalog | None = None,
) -> LoadedScenario:
    resolved_path = path.resolve(strict=True)
    document = _read_scenario_document(resolved_path)
    validate_document("scenario-v1", document)
    _validate_interpolations(document)

    base_dir = resolved_path.parent
    roots = (base_dir,) if workspace_root is None else (base_dir, workspace_root)
    resolver = ContainedSourceResolver(roots)
    resources, agent_profiles = _snapshot_resources(
        document,
        resolver,
        base_dir,
        agent_catalog,
    )
    metadata = cast(Mapping[str, Any], document["metadata"])
    source = ScenarioSource(level=level, path=resolved_path, root=base_dir)
    return LoadedScenario(
        name=str(metadata["name"]),
        document=MappingProxyType(document),
        source=source,
        resources=resources,
        agent_profiles=agent_profiles,
    )


class ScenarioCatalog:
    def __init__(
        self,
        *,
        builtin_dir: Path | None = None,
        user_dir: Path | None = None,
        project_dir: Path | None = None,
        workspace_root: Path | None = None,
        agent_catalog: AgentProfileCatalog | None = None,
    ) -> None:
        self._levels = (
            ("builtin", builtin_dir),
            ("user", user_dir),
            ("project", project_dir),
        )
        self._workspace_root = workspace_root
        self._agent_catalog = agent_catalog

    def _discover_level(
        self,
        level: str,
        directory: Path,
    ) -> dict[str, ScenarioCatalogEntry]:
        if not directory.exists():
            return {}
        root = directory.resolve(strict=True)
        entries: dict[str, ScenarioCatalogEntry] = {}
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if path.suffix.lower() not in _SCENARIO_SUFFIXES:
                continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise AgentRuntimeError(
                    ErrorCode.PATH_NOT_ALLOWED,
                    f"Scenario file escapes catalog root: {path}",
                    details={"path": str(path), "root": str(root)},
                )
            scenario = load_scenario_file(
                resolved,
                level=level,
                workspace_root=self._workspace_root,
                agent_catalog=self._agent_catalog,
            )
            if scenario.name in entries:
                raise AgentRuntimeError(
                    ErrorCode.SCENARIO_INVALID,
                    f"Duplicate scenario name in {level} catalog: {scenario.name}",
                    details={"name": scenario.name, "level": level},
                )
            metadata = cast(Mapping[str, Any], scenario.document["metadata"])
            entries[scenario.name] = ScenarioCatalogEntry(
                name=scenario.name,
                title=str(metadata["title"]),
                source=scenario.source,
                scenario=scenario,
            )
        return entries

    def discover(self) -> Mapping[str, ScenarioCatalogEntry]:
        merged: dict[str, ScenarioCatalogEntry] = {}
        for level, directory in self._levels:
            if directory is not None:
                merged.update(self._discover_level(level, directory))
        return MappingProxyType(merged)

    def load(self, name: str) -> LoadedScenario:
        entry = self.discover().get(name)
        if entry is None:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Scenario not found: {name}",
                details={"name": name},
            )
        return entry.scenario
