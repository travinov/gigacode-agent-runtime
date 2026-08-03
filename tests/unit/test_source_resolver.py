from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.source_resolver import ContainedSourceResolver


def test_file_inside_allowed_root_is_read(tmp_path: Path) -> None:
    root = tmp_path / "scenario"
    root.mkdir()
    prompt = root / "prompt.md"
    prompt.write_text("safe")
    resolver = ContainedSourceResolver((root,))

    resource = resolver.read_text("prompt.md", base_dir=root)

    assert resource.content == "safe"
    assert resource.path == prompt.resolve()


def test_parent_traversal_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "scenario"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside")
    resolver = ContainedSourceResolver((root,))

    with pytest.raises(AgentRuntimeError) as captured:
        resolver.read_text("../outside.md", base_dir=root)

    assert captured.value.code is ErrorCode.PATH_NOT_ALLOWED


def test_symlink_escape_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "scenario"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside")
    (root / "link.md").symlink_to(outside)
    resolver = ContainedSourceResolver((root,))

    with pytest.raises(AgentRuntimeError) as captured:
        resolver.read_text("link.md", base_dir=root)

    assert captured.value.code is ErrorCode.PATH_NOT_ALLOWED


def test_absolute_path_outside_roots_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "scenario"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside")
    resolver = ContainedSourceResolver((root,))

    with pytest.raises(AgentRuntimeError) as captured:
        resolver.read_text(str(outside), base_dir=root)

    assert captured.value.code is ErrorCode.PATH_NOT_ALLOWED
