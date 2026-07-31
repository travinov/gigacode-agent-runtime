"""Installed read-only scenario catalog locations."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from .agent_catalog import AgentProfileCatalog
from .config import EffectiveConfig
from .scenario_loader import ScenarioCatalog
from .skill_catalog import SkillProfileCatalog


def builtin_catalog_root() -> Path:
    return Path(str(files("gigacode_agent_runtime").joinpath("_catalog")))


def builtin_scenarios_dir() -> Path:
    return builtin_catalog_root() / "scenarios"


def create_scenario_catalog(
    config: EffectiveConfig,
    *,
    project_dir: Path | None = None,
    workspace_root: Path | None = None,
) -> ScenarioCatalog:
    agent_catalog = create_agent_profile_catalog(config)
    skill_catalog = create_skill_profile_catalog(config)
    return ScenarioCatalog(
        builtin_dir=builtin_scenarios_dir(),
        user_dir=config.paths.user_scenarios,
        project_dir=project_dir,
        workspace_root=workspace_root,
        agent_catalog=agent_catalog,
        skill_catalog=skill_catalog,
    )


def create_agent_profile_catalog(config: EffectiveConfig) -> AgentProfileCatalog:
    return AgentProfileCatalog(config.paths.home / ".gigacode" / "agents")


def create_skill_profile_catalog(config: EffectiveConfig) -> SkillProfileCatalog:
    gigacode_home = config.paths.home / ".gigacode"
    return SkillProfileCatalog(
        gigacode_home / "skills",
        extension_root=gigacode_home / "extensions",
        bundled_root=gigacode_home / "bin" / "bundled",
    )
