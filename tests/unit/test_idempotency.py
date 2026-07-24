from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.idempotency import IdempotencyStore


def test_same_key_and_signature_returns_existing_run(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path)
    calls = 0

    def create() -> str:
        nonlocal calls
        calls += 1
        return "run_existing"

    first = store.get_or_create("request-1", "signature-a", create)
    second = store.get_or_create("request-1", "signature-a", create)

    assert first == second == "run_existing"
    assert calls == 1


def test_same_key_with_different_signature_is_conflict(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path)
    store.get_or_create("request-1", "signature-a", lambda: "run_first")

    with pytest.raises(AgentRuntimeError) as captured:
        store.get_or_create("request-1", "signature-b", lambda: "run_second")

    assert captured.value.code is ErrorCode.IDEMPOTENCY_CONFLICT
