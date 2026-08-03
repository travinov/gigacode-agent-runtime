from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.skill_catalog import (
    SkillProfileCatalog,
    load_skill_profile,
    skill_name_from_reference,
)


def _skill(name: str = "requirements-review", *, extra: str = "") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        "description: Review requirements for omissions.\n"
        f"{extra}"
        "---\n\n"
        "# Requirements Review\n\nReturn a structured review.\n"
    )


def test_native_skill_is_parsed_with_invocation_metadata(tmp_path: Path) -> None:
    directory = tmp_path / "requirements-review"
    directory.mkdir()
    path = directory / "SKILL.md"
    path.write_text(
        _skill(
            extra=(
                "priority: 20\n"
                "user-invocable: false\n"
                "disable-model-invocation: true\n"
                "paths: [docs/**/*.md]\n"
            )
        )
    )

    profile = load_skill_profile(path)

    assert profile.reference == "gigacode:requirements-review"
    assert profile.priority == 20.0
    assert profile.user_invocable is False
    assert profile.disable_model_invocation is True
    assert profile.paths == ("docs/**/*.md",)
    assert profile.instructions.startswith("# Requirements Review")


def test_catalog_discovers_skills_by_front_matter_name(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    directory = root / "arbitrary-directory"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(_skill())

    catalog = SkillProfileCatalog(root)

    assert list(catalog.discover()) == ["requirements-review"]
    assert catalog.load("gigacode:requirements-review").name == "requirements-review"
    assert skill_name_from_reference("gigacode:requirements-review") == (
        "requirements-review"
    )


def test_composite_catalog_discovers_only_active_gigacode_sources(
    tmp_path: Path,
) -> None:
    gigacode = tmp_path / ".gigacode"
    user = gigacode / "skills"
    extensions = gigacode / "extensions"
    bundled = gigacode / "bin" / "bundled"

    canonical = user / "bpmn-architect"
    alias = user / "publish-bpmn-skill"
    drawio = extensions / "publish-drawio-skill"
    service = extensions / "service-extension" / "skills" / "service-analyst"
    review = bundled / "review"
    historical = (
        gigacode
        / "extension-sources"
        / "publish-drawio-skill"
        / "1.0.0"
    )
    for directory in (canonical, alias, drawio, service, review, historical):
        directory.mkdir(parents=True)
    (user / "SKILL.md").write_text(_skill("root-manifest"))
    (canonical / "SKILL.md").write_text(_skill("bpmn-architect"))
    (alias / "SKILL.md").write_text(_skill("bpmn-architect"))
    (drawio / "SKILL.md").write_text(_skill("drawio-skill"))
    (service / "SKILL.md").write_text(_skill("service-analyst"))
    (review / "SKILL.md").write_text(_skill("review"))
    (historical / "SKILL.md").write_text(_skill("historical-drawio"))

    catalog = SkillProfileCatalog(
        user,
        extension_root=extensions,
        bundled_root=bundled,
    )
    profiles = catalog.discover()

    assert list(profiles) == [
        "bpmn-architect",
        "drawio-skill",
        "review",
        "service-analyst",
    ]
    assert profiles["bpmn-architect"].source_path == (
        canonical / "SKILL.md"
    ).resolve()
    assert profiles["bpmn-architect"].source_level == "user"
    assert [
        profile.source_path
        for profile in profiles["bpmn-architect"].shadowed_profiles
    ] == [(alias / "SKILL.md").resolve()]
    assert profiles["drawio-skill"].source_level == "extension"
    assert profiles["service-analyst"].source_level == "extension"
    assert profiles["review"].source_level == "bundled"
    assert "historical-drawio" not in profiles
    assert "root-manifest" not in profiles


def test_user_skill_overrides_extension_and_bundled_sources(tmp_path: Path) -> None:
    user = tmp_path / "skills"
    extensions = tmp_path / "extensions"
    bundled = tmp_path / "bundled"
    for root in (user, extensions, bundled):
        directory = root / "shared"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(_skill("shared"))

    profile = SkillProfileCatalog(
        user,
        extension_root=extensions,
        bundled_root=bundled,
    ).load("shared")

    assert profile.source_level == "user"
    assert [item.source_level for item in profile.shadowed_profiles] == [
        "extension",
        "bundled",
    ]


def test_missing_skill_has_stable_error(tmp_path: Path) -> None:
    with pytest.raises(AgentRuntimeError) as captured:
        SkillProfileCatalog(tmp_path / "missing").load("missing-skill")

    assert captured.value.code is ErrorCode.SKILL_PROFILE_NOT_FOUND
    assert captured.value.details["name"] == "missing-skill"


@pytest.mark.parametrize(
    "content",
    (
        "No front matter\n",
        "---\nname: skill\ndescription: present\n---\n",
        "---\nname: bad/name\ndescription: present\n---\nInstructions\n",
        "---\nname: skill\ndescription: present\npaths: docs/**\n---\nInstructions\n",
        "---\nname: skill\ndescription: present\npriority: .nan\n---\nInstructions\n",
    ),
)
def test_invalid_skill_file_is_rejected(tmp_path: Path, content: str) -> None:
    directory = tmp_path / "invalid"
    directory.mkdir()
    path = directory / "SKILL.md"
    path.write_text(content)

    with pytest.raises(AgentRuntimeError) as captured:
        load_skill_profile(path)

    assert captured.value.code is ErrorCode.SKILL_PROFILE_INVALID


def test_symlinked_skill_directory_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text(_skill("linked"))
    (root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(AgentRuntimeError) as captured:
        SkillProfileCatalog(root).discover()

    assert captured.value.code is ErrorCode.PATH_NOT_ALLOWED
