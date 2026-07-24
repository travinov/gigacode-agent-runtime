from __future__ import annotations

from gigacode_agent_runtime.domain import FailureReason, RetryPolicy
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from gigacode_agent_runtime.retry import classify_failure, retry_delay, should_retry


def test_retry_requires_matching_reason_and_attempt_budget() -> None:
    policy = RetryPolicy(
        max_attempts=3,
        backoff_seconds=(0.1, 0.5),
        retry_on=(FailureReason.INVALID_OUTPUT,),
    )

    assert should_retry(
        policy,
        failure=FailureReason.INVALID_OUTPUT,
        completed_attempt=1,
    )
    assert not should_retry(
        policy,
        failure=FailureReason.PROCESS_ERROR,
        completed_attempt=1,
    )
    assert not should_retry(
        policy,
        failure=FailureReason.INVALID_OUTPUT,
        completed_attempt=3,
    )
    assert retry_delay(policy, completed_attempt=1) == 0.1
    assert retry_delay(policy, completed_attempt=3) == 0.5


def test_typed_adapter_errors_map_to_stable_failure_reasons() -> None:
    assert (
        classify_failure(
            AgentRuntimeError(
                ErrorCode.PROCESS_ERROR,
                "temporary",
                retryable=True,
            )
        )
        is FailureReason.TRANSIENT_CLI_ERROR
    )
    assert (
        classify_failure(AgentRuntimeError(ErrorCode.STEP_OUTPUT_INVALID, "invalid"))
        is FailureReason.INVALID_OUTPUT
    )
