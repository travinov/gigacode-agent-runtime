from __future__ import annotations

from gigacode_agent_runtime.redaction import Redactor


def test_secret_values_and_bearer_tokens_are_redacted() -> None:
    redactor = Redactor(["exact-secret"])

    redacted = redactor.redact_text(
        "value=exact-secret Authorization: Bearer abc.def-123 token=another-secret"
    )

    assert "exact-secret" not in redacted
    assert "abc.def-123" not in redacted
    assert "another-secret" not in redacted
    assert redacted.count("[REDACTED]") >= 3


def test_empty_secret_is_ignored() -> None:
    redactor = Redactor([""])

    assert redactor.redact_text("ordinary text") == "ordinary text"
