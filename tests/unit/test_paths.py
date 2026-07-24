from __future__ import annotations

from pathlib import Path

from gigacode_agent_runtime.paths import RuntimePaths, resolve_user_path


def test_runtime_paths_use_injected_home() -> None:
    paths = RuntimePaths.for_home(Path("/private/tmp/test-home"))

    assert paths.data_dir == Path("/private/tmp/test-home/.gigacode/agent-runtime")
    assert paths.config_file == paths.data_dir / "config.yaml"
    assert paths.user_scenarios == paths.data_dir / "scenarios"
    assert paths.runs == paths.data_dir / "runs"


def test_tilde_resolution_does_not_read_process_home() -> None:
    resolved = resolve_user_path("~/custom-runtime", Path("/private/tmp/injected-home"))

    assert resolved == Path("/private/tmp/injected-home/custom-runtime")


def test_relative_path_is_resolved_from_explicit_base() -> None:
    resolved = resolve_user_path("state", Path("/private/tmp/injected-home"), base=Path("/work"))

    assert resolved == Path("/work/state")
