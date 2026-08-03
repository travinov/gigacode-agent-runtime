from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from gigacode_agent_runtime.config import load_config
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.studio import StudioService


def _service(tmp_path: Path, *, now: Any = None) -> StudioService:
    home = tmp_path / "home"
    home.mkdir()
    config_path = home / ".gigacode" / "agent-runtime" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "schema_version: gigacode-agent-runtime/config-v1\n"
        "gigacode:\n"
        "  model_allowlist: [code-model-id]\n",
        encoding="utf-8",
    )
    project_scenarios = tmp_path / "workspace" / ".gigacode" / "scenarios"
    kwargs = {"now": now} if now is not None else {}
    return StudioService(
        load_config(config_path, home=home),
        project_scenarios=project_scenarios,
        **kwargs,
    )


def _agent_document(name: str = "reviewer") -> dict[str, object]:
    return {
        "name": name,
        "description": "Reviews a proposed change.",
        "model": "code-model-id",
        "approvalMode": "plan",
        "tools": ["read_file"],
        "disallowedTools": [],
        "system_prompt": "Review the change and return actionable findings.",
    }


def _skill_document(name: str = "review-skill") -> dict[str, object]:
    return {
        "name": name,
        "description": "A repeatable review workflow.",
        "priority": 20,
        "user-invocable": True,
        "disable-model-invocation": False,
        "paths": ["docs/**/*.md"],
        "instructions": "# Review\n\nInspect requirements and report omissions.",
    }


def _scenario_document(name: str = "studio-route") -> dict[str, object]:
    return {
        "schema_version": "gigacode-agent-runtime/scenario-v1",
        "kind": "Scenario",
        "metadata": {"name": name, "title": "Studio route"},
        "inputs": {"task": {"type": "string", "required": True, "default": "Review"}},
        "agents": {
            "analyst": {
                "model": "code-model-id",
                "permissions": "read_only",
                "system_prompt": "Analyze the task.",
            }
        },
        "steps": {
            "analyze": {
                "kind": "agent",
                "agent": "analyst",
                "needs": [],
                "prompt": {"template": "Analyze: ${inputs.task}"},
                "output_schema": {
                    "type": "object",
                    "required": ["summary"],
                    "properties": {"summary": {"type": "string"}},
                    "additionalProperties": False,
                },
            }
        },
        "result": {"from": "${steps.analyze.output}"},
    }


def _preview(
    service: StudioService,
    *,
    kind: str,
    scope: str,
    name: str | None,
    document: dict[str, object],
    session: str = "session-a",
) -> dict[str, object]:
    return service.preview(
        {"kind": kind, "scope": scope, "name": name, "document": document},
        session_token=session,
    )


def test_catalog_and_details_cover_managed_sources(tmp_path: Path) -> None:
    service = _service(tmp_path)
    agent_path = service.config.paths.home / ".gigacode" / "agents" / "reviewer.md"
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text(
        "---\nname: reviewer\ndescription: Reviews changes.\n---\n\nReview it.\n",
        encoding="utf-8",
    )
    skill_path = service.config.paths.home / ".gigacode" / "skills" / "review-skill" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "---\nname: review-skill\ndescription: Reviews requirements.\n---\n\nReview.\n",
        encoding="utf-8",
    )
    scenario_path = service.project_scenarios / "studio-route.yaml"  # type: ignore[operator]
    scenario_path.parent.mkdir(parents=True)
    scenario_path.write_text(
        yaml.safe_dump(_scenario_document(), sort_keys=False),
        encoding="utf-8",
    )

    catalog = service.catalog()

    assert catalog["paths"]["project_scenarios"] == str(service.project_scenarios)  # type: ignore[index]
    assert any(item["name"] == "reviewer" for item in catalog["agents"])  # type: ignore[index]
    assert any(item["name"] == "review-skill" for item in catalog["skills"])  # type: ignore[index]
    assert any(item["name"] == "studio-route" for item in catalog["scenarios"])  # type: ignore[index]
    assert service.detail("agent", "user", "reviewer")["writable"] is True
    assert service.detail("skill", "user", "review-skill")["writable"] is True
    assert service.detail("scenario", "project", "studio-route")["writable"] is True


@pytest.mark.parametrize(
    ("kind", "scope", "name", "document", "suffix"),
    (
        ("agent", "user", "reviewer", _agent_document(), "agents/reviewer.md"),
        (
            "skill",
            "user",
            "review-skill",
            _skill_document(),
            "skills/review-skill/SKILL.md",
        ),
        (
            "scenario",
            "project",
            "studio-route",
            _scenario_document(),
            "workspace/.gigacode/scenarios/studio-route.yaml",
        ),
    ),
)
def test_preview_and_apply_use_canonical_formats_and_restrictive_mode(
    tmp_path: Path,
    kind: str,
    scope: str,
    name: str,
    document: dict[str, object],
    suffix: str,
) -> None:
    service = _service(tmp_path)
    preview = _preview(
        service,
        kind=kind,
        scope=scope,
        name=name,
        document=document,
    )

    assert preview["validation"]["valid"] is True  # type: ignore[index]
    assert preview["target_path"].endswith(suffix)  # type: ignore[union-attr]
    assert preview["diff"].startswith("--- ")  # type: ignore[union-attr]
    result = service.apply(str(preview["preview_id"]), session_token="session-a")
    target = Path(str(result["target_path"]))

    assert result["applied"] is True
    assert target.exists()
    assert target.stat().st_mode & 0o777 == 0o600
    if kind in {"agent", "skill"}:
        assert target.read_text(encoding="utf-8").startswith("---\n")
    else:
        assert yaml.safe_load(target.read_text(encoding="utf-8"))["metadata"]["name"] == name


def test_config_preview_applies_exact_selected_source_and_requires_reconnect(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    document = service.config.to_snapshot()
    document["runtime"]["max_parallel_agents"] = 7
    preview = _preview(
        service,
        kind="config",
        scope="selected",
        name=None,
        document=document,
    )

    assert preview["target_path"] == str(service.config.source_path)
    assert "Reconnect" in str(preview["activation"])
    result = service.apply(str(preview["preview_id"]), session_token="session-a")

    assert result["backup_path"] is not None
    updated = load_config(service.config.source_path, home=service.config.paths.home)
    assert updated.runtime.max_parallel_agents == 7


def test_existing_agent_and_skill_keep_their_discovered_source_paths(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    agent = service.config.paths.home / ".gigacode" / "agents" / "custom-file.md"
    agent.parent.mkdir(parents=True)
    agent.write_text(
        "---\nname: reviewer\ndescription: Existing agent.\n---\n\nReview.\n",
        encoding="utf-8",
    )
    skill = service.config.paths.home / ".gigacode" / "skills" / "custom-directory" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: review-skill\ndescription: Existing Skill.\n---\n\nReview.\n",
        encoding="utf-8",
    )

    agent_preview = _preview(
        service,
        kind="agent",
        scope="user",
        name="reviewer",
        document=_agent_document(),
    )
    skill_preview = _preview(
        service,
        kind="skill",
        scope="user",
        name="review-skill",
        document=_skill_document(),
    )

    assert agent_preview["target_path"] == str(agent.resolve())
    assert skill_preview["target_path"] == str(skill.resolve())


def test_preview_is_session_bound_expires_and_cannot_be_replayed(tmp_path: Path) -> None:
    clock = [100.0]
    service = _service(tmp_path, now=lambda: clock[0])
    preview = _preview(
        service,
        kind="agent",
        scope="user",
        name="reviewer",
        document=_agent_document(),
    )

    with pytest.raises(AgentRuntimeError) as wrong_session:
        service.apply(str(preview["preview_id"]), session_token="session-b")
    assert wrong_session.value.code is ErrorCode.PERMISSION_DENIED

    service.apply(str(preview["preview_id"]), session_token="session-a")
    with pytest.raises(AgentRuntimeError) as replayed:
        service.apply(str(preview["preview_id"]), session_token="session-a")
    assert replayed.value.code is ErrorCode.INVALID_STATE_TRANSITION

    expiring = _preview(
        service,
        kind="agent",
        scope="user",
        name="second",
        document=_agent_document("second"),
    )
    clock[0] += 601
    with pytest.raises(AgentRuntimeError) as expired:
        service.apply(str(expiring["preview_id"]), session_token="session-a")
    assert expired.value.code is ErrorCode.INVALID_STATE_TRANSITION


def test_apply_detects_optimistic_conflict_and_keeps_external_content(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    preview = _preview(
        service,
        kind="agent",
        scope="user",
        name="reviewer",
        document=_agent_document(),
    )
    target = Path(str(preview["target_path"]))
    target.parent.mkdir(parents=True)
    target.write_text("external edit\n", encoding="utf-8")

    with pytest.raises(AgentRuntimeError) as conflict:
        service.apply(str(preview["preview_id"]), session_token="session-a")

    assert conflict.value.code is ErrorCode.PLAN_CONFLICT
    assert target.read_text(encoding="utf-8") == "external edit\n"


def test_apply_creates_backup_and_rolls_back_failed_post_write_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    target = service.config.paths.home / ".gigacode" / "agents" / "reviewer.md"
    target.parent.mkdir(parents=True)
    original = "---\nname: reviewer\ndescription: Original.\n---\n\nOriginal prompt.\n"
    target.write_text(original, encoding="utf-8")
    preview = _preview(
        service,
        kind="agent",
        scope="user",
        name="reviewer",
        document=_agent_document(),
    )

    def fail_validation(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AgentRuntimeError(ErrorCode.AGENT_PROFILE_INVALID, "forced failure")

    monkeypatch.setattr(service, "_validate_persisted", fail_validation)
    with pytest.raises(AgentRuntimeError) as failed:
        service.apply(str(preview["preview_id"]), session_token="session-a")

    assert failed.value.code is ErrorCode.AGENT_PROFILE_INVALID
    assert target.read_text(encoding="utf-8") == original
    backups = list((service.config.runtime.data_dir / "studio-backups").rglob("*reviewer.md"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original


def test_managed_name_and_symlink_guards_block_path_escape(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(AgentRuntimeError) as invalid_name:
        _preview(
            service,
            kind="agent",
            scope="user",
            name="../outside",
            document=_agent_document("../outside"),
        )
    assert invalid_name.value.code is ErrorCode.CONFIG_INVALID

    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    linked = service.config.paths.home / ".gigacode" / "agents" / "linked.md"
    linked.parent.mkdir(parents=True, exist_ok=True)
    linked.symlink_to(outside)
    with pytest.raises(AgentRuntimeError) as symlinked:
        _preview(
            service,
            kind="agent",
            scope="user",
            name="linked",
            document=_agent_document("linked"),
        )

    assert symlinked.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert outside.read_text(encoding="utf-8") == "outside\n"
    assert os.path.islink(linked)
