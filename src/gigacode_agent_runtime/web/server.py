"""Starlette application and pre-bound localhost Uvicorn server."""

from __future__ import annotations

import json
import mimetypes
import socket
from collections.abc import AsyncIterator
from functools import partial
from importlib.resources import files
from pathlib import Path

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route

from ..domain import RunStatus
from ..errors import AgentRuntimeError, ErrorCode
from ..event_log import EventLog
from ..mcp_tools import McpToolService
from ..state_store import StateStore
from .api import DashboardApi
from .auth import SESSION_COOKIE, DashboardAuth, DashboardSession
from .sse import encode_event, encode_heartbeat, parse_cursor

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)
_TERMINAL = {
    RunStatus.COMPLETED,
    RunStatus.COMPLETED_BEST_EFFORT,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.INTERRUPTED,
    RunStatus.PAUSED,
    RunStatus.WAITING_FOR_APPROVAL,
    RunStatus.WAITING_FOR_INPUT,
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response


def _error_response(error: AgentRuntimeError, status: int = 400) -> JSONResponse:
    if error.code is ErrorCode.PERMISSION_DENIED:
        status = 403
    elif error.code is ErrorCode.RUN_NOT_FOUND:
        status = 404
    return JSONResponse({"ok": False, "error": error.to_dict()}, status_code=status)


def _asset_path(name: str) -> Path:
    asset = files("gigacode_agent_runtime.web").joinpath("static", name)
    return Path(str(asset))


def create_dashboard_app(
    tools: McpToolService,
    auth: DashboardAuth,
) -> Starlette:
    api = DashboardApi(tools)

    def session(request: Request, *, csrf: bool = False) -> DashboardSession:
        authenticated = auth.authenticate(request.cookies.get(SESSION_COOKIE))
        if csrf:
            auth.verify_csrf(
                authenticated,
                request.headers.get("x-csrf-token"),
            )
        return authenticated

    async def index(_request: Request) -> Response:
        return FileResponse(_asset_path("index.html"), media_type="text/html")

    async def asset(request: Request) -> Response:
        name = request.path_params["name"]
        if name not in {"app.js", "styles.css", "icons.svg"}:
            return Response(status_code=404)
        media_type, _encoding = mimetypes.guess_type(name)
        return FileResponse(_asset_path(name), media_type=media_type)

    async def bootstrap(request: Request) -> Response:
        try:
            raw = await request.json()
            token = raw.get("token") if isinstance(raw, dict) else None
            if not isinstance(token, str):
                raise AgentRuntimeError(
                    ErrorCode.PERMISSION_DENIED,
                    "Bootstrap token is required",
                )
            created = auth.exchange(token)
        except AgentRuntimeError as error:
            return _error_response(error)
        response = JSONResponse(
            {
                "ok": True,
                "data": {
                    "csrf_token": created.csrf_token,
                    "expires_at": created.expires_at,
                },
            }
        )
        response.set_cookie(
            SESSION_COOKIE,
            created.session_token,
            httponly=True,
            samesite="strict",
            max_age=3600,
            path="/",
        )
        return response

    async def runs(request: Request) -> Response:
        try:
            session(request)
            limit = int(request.query_params.get("limit", "100"))
            return JSONResponse({"ok": True, "data": api.list_runs(limit=limit)})
        except (AgentRuntimeError, ValueError) as error:
            if isinstance(error, AgentRuntimeError):
                return _error_response(error)
            return _error_response(
                AgentRuntimeError(ErrorCode.CONFIG_INVALID, str(error))
            )

    async def run_status(request: Request) -> Response:
        try:
            session(request)
            return JSONResponse(
                {
                    "ok": True,
                    "data": api.status(request.path_params["run_id"]),
                }
            )
        except AgentRuntimeError as error:
            return _error_response(error)

    async def run_plan(request: Request) -> Response:
        try:
            session(request)
            return JSONResponse(
                {
                    "ok": True,
                    "data": api.plan(request.path_params["run_id"]),
                }
            )
        except AgentRuntimeError as error:
            return _error_response(error)

    async def run_events(request: Request) -> Response:
        try:
            session(request)
            data = await api.events(
                request.path_params["run_id"],
                after=int(request.query_params.get("after", "0")),
                limit=int(request.query_params.get("limit", "100")),
            )
            return JSONResponse({"ok": True, "data": data})
        except (AgentRuntimeError, ValueError) as error:
            if isinstance(error, AgentRuntimeError):
                return _error_response(error)
            return _error_response(
                AgentRuntimeError(ErrorCode.CONFIG_INVALID, str(error))
            )

    async def run_result(request: Request) -> Response:
        try:
            session(request)
            return JSONResponse(
                {
                    "ok": True,
                    "data": await api.result(request.path_params["run_id"]),
                }
            )
        except AgentRuntimeError as error:
            return _error_response(error)

    async def run_artifacts(request: Request) -> Response:
        try:
            session(request)
            data = await api.artifacts(
                request.path_params["run_id"],
                after=int(request.query_params.get("after", "0")),
                limit=int(request.query_params.get("limit", "100")),
            )
            return JSONResponse({"ok": True, "data": data})
        except (AgentRuntimeError, ValueError) as error:
            if isinstance(error, AgentRuntimeError):
                return _error_response(error)
            return _error_response(
                AgentRuntimeError(ErrorCode.CONFIG_INVALID, str(error))
            )

    async def control(request: Request) -> Response:
        try:
            session(request, csrf=True)
            raw = await request.json()
            payload = raw if isinstance(raw, dict) else {}
            data = await api.control(
                request.path_params["action"],
                request.path_params["run_id"],
                payload,
            )
            return JSONResponse({"ok": True, "data": data})
        except (AgentRuntimeError, ValueError, json.JSONDecodeError) as error:
            if isinstance(error, AgentRuntimeError):
                return _error_response(error)
            return _error_response(
                AgentRuntimeError(ErrorCode.CONFIG_INVALID, str(error))
            )

    async def stream(request: Request) -> Response:
        try:
            session(request)
            run_id = request.path_params["run_id"]
            states = StateStore(tools.config.paths.runs)
            states.read(run_id)
            events = EventLog(states.run_dir(run_id), run_id=run_id)
            cursor = parse_cursor(
                request.headers.get("last-event-id"),
                request.query_params.get("cursor"),
            )
        except AgentRuntimeError as error:
            return _error_response(error)

        async def generate() -> AsyncIterator[str]:
            nonlocal cursor
            while True:
                page = events.read(after=cursor, limit=100)
                for event in page.events:
                    cursor = event.event_id
                    yield encode_event(event)
                state = states.read(run_id)
                if state.status in _TERMINAL and not page.has_more:
                    return
                await anyio.sleep(1)
                if await request.is_disconnected():
                    return
                yield encode_heartbeat(cursor)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    routes = [
        Route("/", index),
        Route("/assets/{name}", asset),
        Route("/api/bootstrap", bootstrap, methods=["POST"]),
        Route("/api/runs", runs),
        Route("/api/runs/{run_id}", run_status),
        Route("/api/runs/{run_id}/plan", run_plan),
        Route("/api/runs/{run_id}/events", run_events),
        Route("/api/runs/{run_id}/result", run_result),
        Route("/api/runs/{run_id}/artifacts", run_artifacts),
        Route("/api/runs/{run_id}/stream", stream),
        Route(
            "/api/runs/{run_id}/{action}",
            control,
            methods=["POST"],
        ),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


class LocalWebServer:
    def __init__(
        self,
        tools: McpToolService,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
    ) -> None:
        if host != "127.0.0.1":
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                "Dashboard may bind only to 127.0.0.1",
                details={"host": host},
            )
        self.auth = DashboardAuth()
        self.app = create_dashboard_app(tools, self.auth)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((host, port or 0))
        self._socket.listen(128)
        self._socket.setblocking(False)
        self.host = host
        self.port = int(self._socket.getsockname()[1])
        self._server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                log_level="error",
                access_log=False,
                lifespan="off",
            )
        )
        self._task_group: anyio.abc.TaskGroup | None = None

    def url(self, run_id: str | None = None) -> str:
        suffix = f"?run={run_id}" if run_id is not None else ""
        return (
            f"http://{self.host}:{self.port}/{suffix}"
            f"#token={self.auth.issue_bootstrap_token()}"
        )

    async def start(self) -> None:
        if self._task_group is not None:
            return
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        self._task_group.start_soon(
            partial(self._server.serve, sockets=[self._socket])
        )
        with anyio.fail_after(5):
            while not self._server.started:
                await anyio.sleep(0.01)

    async def stop(self) -> None:
        if self._task_group is None:
            self._socket.close()
            return
        self._server.should_exit = True
        task_group = self._task_group
        self._task_group = None
        await task_group.__aexit__(None, None, None)
        self._socket.close()
