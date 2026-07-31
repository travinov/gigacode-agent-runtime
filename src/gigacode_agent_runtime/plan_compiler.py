"""Compile validated scenarios into immutable deterministic execution plans."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .config import EffectiveConfig
from .dag import topological_waves
from .domain import (
    AgentDefinition,
    AgentStepDefinition,
    ExecutionPlan,
    FailureReason,
    LoopStepDefinition,
    OnLimit,
    PermissionMode,
    PromptDefinition,
    RetryPolicy,
    ScenarioMetadata,
    ScenarioSource,
    SkillDefinition,
)
from .errors import AgentRuntimeError, ErrorCode
from .hashing import json_object, sha256_digest
from .interpolation import extract_references
from .scenario_loader import LoadedScenario
from .schema_registry import validate_document
from .version import EXECUTION_PLAN_SCHEMA_VERSION

_DEFAULT_LOOP_ITERATIONS = 10
_EMPTY_PLAN_HASH = "sha256:" + ("0" * 64)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return cast(Mapping[str, object], _freeze(value))


def _validate_input_type(name: str, expected: str, value: object) -> None:
    valid = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, Mapping),
        "array": isinstance(value, (list, tuple)),
    }[expected]
    if not valid:
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            f"Input '{name}' must have type {expected}",
            details={"input": name, "expected_type": expected},
        )


def _resolve_inputs(
    document: Mapping[str, Any],
    supplied: Mapping[str, object],
) -> Mapping[str, object]:
    definitions = cast(Mapping[str, Mapping[str, Any]], document.get("inputs", {}))
    unknown = sorted(set(supplied) - set(definitions))
    if unknown:
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            f"Unknown scenario input: {unknown[0]}",
            details={"input": unknown[0]},
        )

    resolved: dict[str, object] = {}
    for name in sorted(definitions):
        definition = definitions[name]
        if name in supplied:
            value = supplied[name]
        elif "default" in definition:
            value = definition["default"]
        elif bool(definition.get("required", False)):
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Required scenario input is missing: {name}",
                details={"input": name},
            )
        else:
            continue
        _validate_input_type(name, str(definition["type"]), value)
        resolved[name] = _freeze(value)
    return MappingProxyType(resolved)


def _resource_text(scenario: LoadedScenario, reference: str) -> str:
    resource = scenario.resources.get(reference)
    if resource is None:
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            f"Scenario resource was not snapshotted: {reference}",
            details={"reference": reference},
        )
    return resource.content


def _compile_agents(
    scenario: LoadedScenario,
    config: EffectiveConfig,
) -> Mapping[str, AgentDefinition]:
    raw_agents = cast(Mapping[str, Mapping[str, Any]], scenario.document["agents"])
    agents: dict[str, AgentDefinition] = {}
    allowed_models = set(config.gigacode.model_allowlist)
    for name in sorted(raw_agents):
        raw = raw_agents[name]
        model = str(raw["model"])
        if model.startswith("REPLACE_WITH_"):
            raise AgentRuntimeError(
                ErrorCode.MODEL_NOT_ALLOWED,
                f"Agent '{name}' still uses a placeholder model ID: {model}",
                details={
                    "agent": name,
                    "model": model,
                    "placeholder": True,
                },
            )
        if allowed_models and model not in allowed_models:
            raise AgentRuntimeError(
                ErrorCode.MODEL_NOT_ALLOWED,
                f"Model is not in the configured allowlist: {model}",
                details={"agent": name, "model": model},
            )
        source_ref: str | None = None
        source_hash: str | None = None
        profile_tools: tuple[str, ...] = ()
        if "system_prompt" in raw:
            system_prompt = str(raw["system_prompt"])
        elif "system_prompt_file" in raw:
            system_prompt = _resource_text(scenario, str(raw["system_prompt_file"]))
        else:
            source_ref = str(raw["agent_ref"])
            profile = scenario.agent_profiles.get(source_ref)
            if profile is None:
                raise AgentRuntimeError(
                    ErrorCode.AGENT_PROFILE_NOT_FOUND,
                    f"GigaCode agent profile was not snapshotted: {source_ref}",
                    details={"agent_ref": source_ref},
                )
            system_prompt = profile.system_prompt
            source_hash = sha256_digest(profile.raw_content)
            profile_tools = tuple(
                tool for tool in profile.tools if tool not in profile.disallowed_tools
            )
        skills: list[SkillDefinition] = []
        skill_sections: list[str] = []
        for raw_skill_ref in cast(list[object], raw.get("skill_refs", [])):
            skill_ref = str(raw_skill_ref)
            skill = scenario.skill_profiles.get(skill_ref)
            if skill is None:
                raise AgentRuntimeError(
                    ErrorCode.SKILL_PROFILE_NOT_FOUND,
                    f"GigaCode Skill was not snapshotted: {skill_ref}",
                    details={"agent": name, "skill_ref": skill_ref},
                )
            skill_hash = sha256_digest(skill.raw_content)
            skills.append(
                SkillDefinition(
                    name=skill.name,
                    reference=skill.reference,
                    description=skill.description,
                    base_dir=skill.base_dir,
                    source_hash=skill_hash,
                )
            )
            skill_sections.append(
                f"### Skill: {skill.name}\n"
                f"Reference: {skill.reference}\n"
                f"Base directory: {skill.base_dir}\n"
                f"Description: {skill.description}\n\n"
                f"{skill.instructions}"
            )
        if skill_sections:
            system_prompt = (
                f"{system_prompt.rstrip()}\n\n"
                "## Runtime-selected GigaCode Skills\n"
                "Only the Skills listed in this section are authorized for this "
                "agent. Apply a Skill when it is relevant to the task. Do not load "
                "or invoke any other Skill. Resolve relative paths in a Skill from "
                "its declared Base directory. If the current permission mode does "
                "not provide a required tool, follow the available instructions but "
                "do not attempt the prohibited operation.\n\n"
                + "\n\n---\n\n".join(skill_sections)
            )
        agents[name] = AgentDefinition(
            name=name,
            model=model,
            permissions=PermissionMode(str(raw["permissions"])),
            system_prompt=system_prompt,
            allowed_tools=(
                tuple(str(item) for item in raw["allowed_tools"])
                if "allowed_tools" in raw
                else profile_tools
            ),
            source_ref=source_ref,
            source_hash=source_hash,
            skills=tuple(skills),
        )
    return MappingProxyType(agents)


def _compile_retry(raw: object) -> RetryPolicy:
    if not isinstance(raw, Mapping):
        return RetryPolicy()
    retry_on = tuple(FailureReason(str(value)) for value in raw.get("on", []))
    return RetryPolicy(
        max_attempts=int(raw["max_attempts"]),
        backoff_seconds=tuple(float(value) for value in raw.get("backoff_seconds", [])),
        retry_on=retry_on,
    )


def _compile_output_schema(scenario: LoadedScenario, raw: object) -> Mapping[str, object]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(_resource_text(scenario, raw))
        except json.JSONDecodeError as exc:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Output schema is not valid JSON: {raw}",
                details={"reference": raw},
            ) from exc
    else:
        parsed = raw
    if not isinstance(parsed, Mapping):
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            "Output schema must be an object",
        )
    try:
        Draft202012Validator.check_schema(parsed)
    except SchemaError as exc:
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            f"Agent output schema is invalid: {exc.message}",
        ) from exc
    return _freeze_mapping(cast(Mapping[str, object], parsed))


def _compile_prompt(
    scenario: LoadedScenario,
    raw: Mapping[str, Any],
) -> PromptDefinition:
    template = (
        str(raw["template"])
        if "template" in raw
        else _resource_text(scenario, str(raw["template_file"]))
    )
    context = cast(Mapping[str, object], raw.get("context", {}))
    return PromptDefinition(template=template, context=_freeze_mapping(context))


def _compile_agent_step(
    name: str,
    raw: Mapping[str, Any],
    *,
    scenario: LoadedScenario,
    agents: Mapping[str, AgentDefinition],
    default_timeout: int,
) -> AgentStepDefinition:
    agent_name = str(raw["agent"])
    if agent_name not in agents:
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            f"Step '{name}' references unknown agent '{agent_name}'",
            details={"step": name, "agent": agent_name},
        )
    condition_raw = raw.get("when")
    condition = (
        _freeze_mapping(cast(Mapping[str, object], condition_raw))
        if isinstance(condition_raw, Mapping)
        else None
    )
    return AgentStepDefinition(
        name=name,
        agent=agent_name,
        needs=tuple(str(item) for item in raw["needs"]),
        prompt=_compile_prompt(scenario, cast(Mapping[str, Any], raw["prompt"])),
        output_schema=_compile_output_schema(scenario, raw["output_schema"]),
        timeout_seconds=int(raw.get("timeout_seconds", default_timeout)),
        retry=_compile_retry(raw.get("retry")),
        condition=condition,
    )


def _references_in(value: object) -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, str):
        found.extend(extract_references(value))
    elif isinstance(value, Mapping):
        for nested in value.values():
            found.extend(_references_in(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.extend(_references_in(nested))
    return tuple(found)


def _validate_reference_targets(
    document: Mapping[str, Any],
    input_names: set[str],
) -> None:
    step_names = set(cast(Mapping[str, Any], document["steps"]))
    values: list[object] = [document["result"]]
    for raw_step in cast(Mapping[str, Any], document["steps"]).values():
        step = cast(Mapping[str, Any], raw_step)
        values.extend([step.get("when"), step.get("until"), step.get("no_progress")])
        if step["kind"] == "agent":
            values.append(step["prompt"])
        else:
            body = cast(Mapping[str, Any], step["body"])
            for raw_body_step in cast(Mapping[str, Any], body["steps"]).values():
                body_step = cast(Mapping[str, Any], raw_body_step)
                values.extend([body_step["prompt"], body_step.get("when")])

    for reference in _references_in(values):
        parts = reference.split(".")
        if parts[0] == "inputs" and parts[1] not in input_names:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Reference uses unknown input: {parts[1]}",
                details={"input": parts[1], "reference": reference},
            )
        if parts[0] == "steps" and parts[1] not in step_names:
            raise AgentRuntimeError(
                ErrorCode.SCENARIO_INVALID,
                f"Reference uses unknown step: {parts[1]}",
                details={"step": parts[1], "reference": reference},
            )


def _capability_requirements(agents: Mapping[str, AgentDefinition]) -> tuple[str, ...]:
    capabilities = {"json_output", "model_selection", "prompt", "system_prompt"}
    permissions = {agent.permissions for agent in agents.values()}
    if permissions & {PermissionMode.READ_ONLY, PermissionMode.PROPOSE_ONLY}:
        capabilities.update({"agent_isolation", "approval_default"})
    if PermissionMode.WORKSPACE_WRITE in permissions:
        capabilities.update({"approval_auto_edit", "sandbox"})
    if PermissionMode.FULL_ACCESS in permissions:
        capabilities.update({"approval_auto_edit", "allowed_tools"})
    if any(agent.skills for agent in agents.values()):
        capabilities.add("tool_exclusion")
    return tuple(sorted(capabilities))


def _compile_steps(
    scenario: LoadedScenario,
    agents: Mapping[str, AgentDefinition],
    config: EffectiveConfig,
) -> tuple[tuple[AgentStepDefinition | LoopStepDefinition, ...], tuple[tuple[str, ...], ...]]:
    raw_steps = cast(Mapping[str, Mapping[str, Any]], scenario.document["steps"])
    dependencies = {
        name: tuple(str(item) for item in raw_steps[name]["needs"]) for name in sorted(raw_steps)
    }
    waves = topological_waves(dependencies)
    compiled: list[AgentStepDefinition | LoopStepDefinition] = []
    for name in sorted(raw_steps):
        raw = raw_steps[name]
        if raw["kind"] == "agent":
            compiled.append(
                _compile_agent_step(
                    name,
                    raw,
                    scenario=scenario,
                    agents=agents,
                    default_timeout=config.runtime.default_step_timeout_seconds,
                )
            )
            continue

        body_raw = cast(Mapping[str, Any], raw["body"])
        body_steps_raw = cast(Mapping[str, Mapping[str, Any]], body_raw["steps"])
        body_dependencies = {
            body_name: tuple(str(item) for item in body_steps_raw[body_name]["needs"])
            for body_name in sorted(body_steps_raw)
        }
        body_waves = topological_waves(body_dependencies)
        body_steps = tuple(
            _compile_agent_step(
                body_name,
                body_steps_raw[body_name],
                scenario=scenario,
                agents=agents,
                default_timeout=config.runtime.default_step_timeout_seconds,
            )
            for body_name in sorted(body_steps_raw)
        )
        contains_full_access = any(
            agents[body_step.agent].permissions is PermissionMode.FULL_ACCESS
            for body_step in body_steps
        )
        max_iterations = int(raw.get("max_iterations", _DEFAULT_LOOP_ITERATIONS))
        if contains_full_access:
            max_iterations = min(
                max_iterations,
                config.permissions.max_full_access_loop_iterations,
            )
        timeout_seconds = int(
            raw.get(
                "timeout_seconds",
                config.runtime.default_step_timeout_seconds * max_iterations,
            )
        )
        compiled.append(
            LoopStepDefinition(
                name=name,
                needs=dependencies[name],
                body=body_steps,
                waves=body_waves,
                until=_freeze_mapping(cast(Mapping[str, object], raw["until"])),
                max_iterations=max_iterations,
                timeout_seconds=timeout_seconds,
                on_limit=OnLimit(str(raw.get("on_limit", "fail"))),
                no_progress=(
                    _freeze_mapping(cast(Mapping[str, object], raw["no_progress"]))
                    if "no_progress" in raw
                    else None
                ),
            )
        )
    return tuple(compiled), waves


def _config_hash_document(config: EffectiveConfig) -> dict[str, Any]:
    snapshot = config.to_snapshot()
    permissions = cast(dict[str, Any], snapshot["permissions"])
    permissions["trusted_scenario_hashes"] = {}
    return snapshot


def execution_plan_to_document(plan: ExecutionPlan) -> dict[str, Any]:
    return {
        "schema_version": plan.schema_version,
        "plan_hash": plan.plan_hash,
        "scenario_hash": plan.scenario_hash,
        "config_hash": plan.config_hash,
        "inputs_hash": plan.inputs_hash,
        "scenario_name": plan.metadata.name,
        "scenario_title": plan.metadata.title,
        "source": {
            "level": plan.source.level,
            "path": str(plan.source.path),
            "root": str(plan.source.root),
        },
        "workspace": str(plan.workspace),
        "inputs": json_object(plan.inputs),
        "max_parallel_agents": plan.max_parallel_agents,
        "agents": json_object(plan.agents),
        "steps": cast(list[object], json_object({"steps": plan.steps})["steps"]),
        "waves": [list(wave) for wave in plan.waves],
        "result_reference": plan.result_reference,
        "resource_hashes": dict(plan.resource_hashes),
        "capability_requirements": list(plan.capability_requirements),
    }


def _agent_step_from_document(raw: Mapping[str, Any]) -> AgentStepDefinition:
    retry_raw = cast(Mapping[str, Any], raw["retry"])
    prompt_raw = cast(Mapping[str, Any], raw["prompt"])
    condition = raw.get("condition")
    return AgentStepDefinition(
        name=str(raw["name"]),
        agent=str(raw["agent"]),
        needs=tuple(str(item) for item in raw["needs"]),
        prompt=PromptDefinition(
            template=str(prompt_raw["template"]),
            context=_freeze_mapping(
                cast(Mapping[str, object], prompt_raw.get("context", {}))
            ),
        ),
        output_schema=_freeze_mapping(
            cast(Mapping[str, object], raw["output_schema"])
        ),
        timeout_seconds=(
            int(raw["timeout_seconds"])
            if raw.get("timeout_seconds") is not None
            else None
        ),
        retry=RetryPolicy(
            max_attempts=int(retry_raw["max_attempts"]),
            backoff_seconds=tuple(
                float(value) for value in retry_raw.get("backoff_seconds", [])
            ),
            retry_on=tuple(
                FailureReason(str(value)) for value in retry_raw.get("retry_on", [])
            ),
        ),
        condition=(
            _freeze_mapping(cast(Mapping[str, object], condition))
            if isinstance(condition, Mapping)
            else None
        ),
    )


def execution_plan_from_document(document: Mapping[str, Any]) -> ExecutionPlan:
    """Rehydrate and authenticate the immutable plan used by resume."""

    validate_document("execution-plan-v1", document)
    hash_document = dict(document)
    expected_hash = str(hash_document.pop("plan_hash"))
    hash_document.pop("source")
    actual_hash = sha256_digest(hash_document)
    if actual_hash != expected_hash:
        raise AgentRuntimeError(
            ErrorCode.STATE_CORRUPTED,
            "Execution plan hash does not match its contents",
            details={"expected": expected_hash, "actual": actual_hash},
        )
    try:
        source_raw = cast(Mapping[str, Any], document["source"])
        agents_raw = cast(Mapping[str, Mapping[str, Any]], document["agents"])
        agents = MappingProxyType(
            {
                name: AgentDefinition(
                    name=str(raw["name"]),
                    model=str(raw["model"]),
                    permissions=PermissionMode(str(raw["permissions"])),
                    system_prompt=str(raw["system_prompt"]),
                    allowed_tools=tuple(
                        str(item) for item in raw.get("allowed_tools", [])
                    ),
                    source_ref=(
                        str(raw["source_ref"])
                        if raw.get("source_ref") is not None
                        else None
                    ),
                    source_hash=(
                        str(raw["source_hash"])
                        if raw.get("source_hash") is not None
                        else None
                    ),
                    skills=tuple(
                        SkillDefinition(
                            name=str(item["name"]),
                            reference=str(item["reference"]),
                            description=str(item["description"]),
                            base_dir=Path(str(item["base_dir"])),
                            source_hash=str(item["source_hash"]),
                        )
                        for item in cast(
                            Sequence[Mapping[str, Any]],
                            raw.get("skills", []),
                        )
                    ),
                )
                for name, raw in agents_raw.items()
            }
        )
        steps: list[AgentStepDefinition | LoopStepDefinition] = []
        for raw_value in cast(Sequence[Mapping[str, Any]], document["steps"]):
            raw = raw_value
            if "body" not in raw:
                steps.append(_agent_step_from_document(raw))
                continue
            body = tuple(
                _agent_step_from_document(item)
                for item in cast(Sequence[Mapping[str, Any]], raw["body"])
            )
            steps.append(
                LoopStepDefinition(
                    name=str(raw["name"]),
                    needs=tuple(str(item) for item in raw["needs"]),
                    body=body,
                    waves=tuple(
                        tuple(str(name) for name in wave)
                        for wave in cast(Sequence[Sequence[object]], raw["waves"])
                    ),
                    until=_freeze_mapping(
                        cast(Mapping[str, object], raw["until"])
                    ),
                    max_iterations=int(raw["max_iterations"]),
                    timeout_seconds=int(raw["timeout_seconds"]),
                    on_limit=OnLimit(str(raw["on_limit"])),
                    no_progress=(
                        _freeze_mapping(
                            cast(Mapping[str, object], raw["no_progress"])
                        )
                        if isinstance(raw.get("no_progress"), Mapping)
                        else None
                    ),
                )
            )
        return ExecutionPlan(
            schema_version=str(document["schema_version"]),
            plan_hash=expected_hash,
            scenario_hash=str(document["scenario_hash"]),
            config_hash=str(document["config_hash"]),
            inputs_hash=str(document["inputs_hash"]),
            metadata=ScenarioMetadata(
                name=str(document["scenario_name"]),
                title=str(document["scenario_title"]),
            ),
            source=ScenarioSource(
                level=str(source_raw["level"]),
                path=Path(str(source_raw["path"])),
                root=Path(str(source_raw["root"])),
            ),
            workspace=Path(str(document["workspace"])),
            inputs=_freeze_mapping(
                cast(Mapping[str, object], document["inputs"])
            ),
            agents=agents,
            steps=tuple(steps),
            waves=tuple(
                tuple(str(name) for name in wave)
                for wave in cast(Sequence[Sequence[object]], document["waves"])
            ),
            max_parallel_agents=int(document["max_parallel_agents"]),
            result_reference=str(document["result_reference"]),
            resource_hashes=MappingProxyType(
                {
                    str(name): str(value)
                    for name, value in cast(
                        Mapping[str, object],
                        document["resource_hashes"],
                    ).items()
                }
            ),
            capability_requirements=tuple(
                str(item) for item in document["capability_requirements"]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentRuntimeError(
            ErrorCode.STATE_CORRUPTED,
            "Execution plan snapshot cannot be rehydrated",
        ) from exc


def compile_plan(
    scenario: LoadedScenario,
    config: EffectiveConfig,
    *,
    inputs: Mapping[str, object],
    workspace: Path,
) -> ExecutionPlan:
    document = scenario.document
    resolved_inputs = _resolve_inputs(document, inputs)
    _validate_reference_targets(document, set(cast(Mapping[str, Any], document.get("inputs", {}))))
    agents = _compile_agents(scenario, config)
    steps, waves = _compile_steps(scenario, agents, config)
    scenario_parallelism = int(
        document.get("max_parallel_agents", config.runtime.max_parallel_agents)
    )
    if scenario_parallelism > config.runtime.max_parallel_agents:
        raise AgentRuntimeError(
            ErrorCode.SCENARIO_INVALID,
            "Scenario max_parallel_agents exceeds the global runtime limit",
            details={
                "scenario_limit": scenario_parallelism,
                "global_limit": config.runtime.max_parallel_agents,
            },
        )

    metadata_raw = cast(Mapping[str, Any], document["metadata"])
    metadata = ScenarioMetadata(
        name=str(metadata_raw["name"]),
        title=str(metadata_raw["title"]),
        description=(
            str(metadata_raw["description"]) if "description" in metadata_raw else None
        ),
    )
    resources_for_hash = {
        reference: resource.content for reference, resource in scenario.resources.items()
    }
    resource_hashes = MappingProxyType(
        {
            reference: sha256_digest(resource.content)
            for reference, resource in sorted(scenario.resources.items())
        }
    )
    plan = ExecutionPlan(
        schema_version=EXECUTION_PLAN_SCHEMA_VERSION,
        plan_hash=_EMPTY_PLAN_HASH,
        scenario_hash=sha256_digest(
            {"document": document, "resources": resources_for_hash}
        ),
        config_hash=sha256_digest(_config_hash_document(config)),
        inputs_hash=sha256_digest(resolved_inputs),
        metadata=metadata,
        source=scenario.source,
        workspace=workspace.resolve(strict=False),
        inputs=resolved_inputs,
        agents=agents,
        steps=steps,
        waves=waves,
        max_parallel_agents=scenario_parallelism,
        result_reference=str(cast(Mapping[str, Any], document["result"])["from"]),
        resource_hashes=resource_hashes,
        capability_requirements=_capability_requirements(agents),
    )
    plan_document = execution_plan_to_document(plan)
    del plan_document["plan_hash"]
    del plan_document["source"]
    return replace(plan, plan_hash=sha256_digest(plan_document))
