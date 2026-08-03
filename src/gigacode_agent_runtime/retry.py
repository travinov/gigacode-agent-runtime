"""Retry classification and deterministic backoff calculation."""

from __future__ import annotations

from .domain import FailureReason, RetryPolicy
from .errors import AgentRuntimeError, ErrorCode


def classify_failure(error: BaseException) -> FailureReason:
    if not isinstance(error, AgentRuntimeError):
        return FailureReason.INTERNAL_ERROR
    if error.code is ErrorCode.PROCESS_TIMEOUT:
        return FailureReason.TIMEOUT
    if error.code is ErrorCode.STEP_OUTPUT_INVALID:
        return FailureReason.INVALID_OUTPUT
    if error.code is ErrorCode.PROCESS_ERROR:
        return (
            FailureReason.TRANSIENT_CLI_ERROR
            if error.retryable
            else FailureReason.PROCESS_ERROR
        )
    if error.code in {ErrorCode.PERMISSION_DENIED, ErrorCode.APPROVAL_REQUIRED}:
        return FailureReason.PERMISSION_DENIED
    return FailureReason.INTERNAL_ERROR


def should_retry(
    policy: RetryPolicy,
    *,
    failure: FailureReason,
    completed_attempt: int,
) -> bool:
    return (
        completed_attempt < policy.max_attempts
        and failure in policy.retry_on
    )


def retry_delay(policy: RetryPolicy, *, completed_attempt: int) -> float:
    if not policy.backoff_seconds:
        return 0.0
    index = min(completed_attempt - 1, len(policy.backoff_seconds) - 1)
    return policy.backoff_seconds[index]
