"""Installed read-only scenario catalog locations."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from .config import EffectiveConfig
from .scenario_loader import ScenarioCatalog


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
    return ScenarioCatalog(
        builtin_dir=builtin_scenarios_dir(),
        user_dir=config.paths.user_scenarios,
        project_dir=project_dir,
        workspace_root=workspace_root,
    )
