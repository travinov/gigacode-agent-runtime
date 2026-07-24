"""One-time bootstrap and short-lived local dashboard sessions."""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

from ..errors import AgentRuntimeError, ErrorCode

SESSION_COOKIE = "gar_session"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DashboardSession:
    session_token: str
    csrf_token: str
    expires_at: float


class DashboardAuth:
    def __init__(self, *, session_ttl_seconds: int = 3600) -> None:
        self._bootstrap_token = secrets.token_urlsafe(32)
        self._bootstrap_digest = _digest(self._bootstrap_token)
        self._bootstrap_used = False
        self._session_ttl_seconds = session_ttl_seconds
        self._sessions: dict[str, DashboardSession] = {}

    @property
    def bootstrap_token(self) -> str:
        return self._bootstrap_token

    def issue_bootstrap_token(self) -> str:
        if self._bootstrap_used:
            self._bootstrap_token = secrets.token_urlsafe(32)
            self._bootstrap_digest = _digest(self._bootstrap_token)
            self._bootstrap_used = False
        return self._bootstrap_token

    def exchange(self, token: str) -> DashboardSession:
        if self._bootstrap_used or not secrets.compare_digest(
            _digest(token),
            self._bootstrap_digest,
        ):
            raise AgentRuntimeError(
                ErrorCode.PERMISSION_DENIED,
                "Dashboard bootstrap token is invalid or already used",
            )
        self._bootstrap_used = True
        session_token = secrets.token_urlsafe(32)
        session = DashboardSession(
            session_token=session_token,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=time.time() + self._session_ttl_seconds,
        )
        self._sessions[_digest(session_token)] = session
        return session

    def authenticate(self, session_token: str | None) -> DashboardSession:
        if not session_token:
            raise AgentRuntimeError(
                ErrorCode.PERMISSION_DENIED,
                "Dashboard session is required",
            )
        session = self._sessions.get(_digest(session_token))
        if session is None or session.expires_at <= time.time():
            raise AgentRuntimeError(
                ErrorCode.PERMISSION_DENIED,
                "Dashboard session is invalid or expired",
            )
        return session

    def verify_csrf(self, session: DashboardSession, token: str | None) -> None:
        if token is None or not secrets.compare_digest(session.csrf_token, token):
            raise AgentRuntimeError(
                ErrorCode.PERMISSION_DENIED,
                "CSRF token is invalid",
            )
