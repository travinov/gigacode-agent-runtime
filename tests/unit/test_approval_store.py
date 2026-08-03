from __future__ import annotations

from pathlib import Path

from gigacode_agent_runtime.approval_store import ApprovalStore


def test_approval_is_bound_to_exact_run_plan_and_gate(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path)
    plan_hash = "sha256:" + ("a" * 64)

    store.approve("run_example", plan_hash, "full_access")

    assert store.is_approved("run_example", plan_hash, "full_access") is True
    assert store.is_approved("run_example", "sha256:" + ("b" * 64), "full_access") is False
    assert store.is_approved("run_example", plan_hash, "other_gate") is False


def test_approval_file_contains_no_prompt_or_environment(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path)
    store.approve("run_example", "sha256:" + ("a" * 64), "full_access")

    content = (tmp_path / "approvals.json").read_text()

    assert "prompt" not in content.lower()
    assert "environment" not in content.lower()
