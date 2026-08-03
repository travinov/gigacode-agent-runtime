"""Authenticated localhost-only configuration Studio server."""

from __future__ import annotations

import json
import mimetypes
import socket
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from ..errors import AgentRuntimeError, ErrorCode
from ..studio import StudioService
from .auth import (
    STUDIO_SESSION_COOKIE,
    DashboardAuth,
    DashboardSession,
)
from .server import SecurityHeadersMiddleware, _error_response

_MAX_REQUEST_BYTES = 2 * 1024 * 1024 + 16 * 1024
_ASSETS = {"app.js", "help.js", "styles.css", "icons.svg"}


def _asset_path(name: str) -> Path:
    asset = files("gigacode_agent_runtime.web").joinpath("studio_static", name)
    return Path(str(asset))


async def _json_object(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_REQUEST_BYTES:
        raise AgentRuntimeError(
            ErrorCode.CONFIG_INVALID,
            "Studio request exceeds the 2 MiB draft limit",
            details={"size": len(raw)},
        )
    try:
        loaded = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AgentRuntimeError(
            ErrorCode.CONFIG_INVALID,
            "Studio request body must be a JSON object",
        ) from exc
    if not isinstance(loaded, dict):
        raise AgentRuntimeError(
            ErrorCode.CONFIG_INVALID,
            "Studio request body must be a JSON object",
        )
    return cast(dict[str, Any], loaded)


def _studio_error(error: AgentRuntimeError) -> JSONResponse:
    status = 409 if error.code is ErrorCode.PLAN_CONFLICT else 400
    return _error_response(error, status=status)


def create_studio_app(
    service: StudioService,
    auth: DashboardAuth,
) -> Starlette:
    """Create a Studio app with an auth authority distinct from the dashboard."""

    def session(request: Request, *, csrf: bool = False) -> DashboardSession:
        authenticated = auth.authenticate(request.cookies.get(STUDIO_SESSION_COOKIE))
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
        if name not in _ASSETS:
            return Response(status_code=404)
        media_type, _encoding = mimetypes.guess_type(name)
        return FileResponse(_asset_path(name), media_type=media_type)

    async def bootstrap(request: Request) -> Response:
        try:
            payload = await _json_object(request)
            token = payload.get("token")
            if not isinstance(token, str):
                raise AgentRuntimeError(
                    ErrorCode.PERMISSION_DENIED,
                    "Bootstrap token is required",
                )
            created = auth.exchange(token)
        except AgentRuntimeError as error:
            return _studio_error(error)
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
            STUDIO_SESSION_COOKIE,
            created.session_token,
            httponly=True,
            samesite="strict",
            max_age=3600,
            path="/",
        )
        return response

    async def catalog(request: Request) -> Response:
        try:
            session(request)
            return JSONResponse({"ok": True, "data": service.catalog()})
        except AgentRuntimeError as error:
            return _studio_error(error)

    async def current_session(request: Request) -> Response:
        try:
            authenticated = session(request)
            return JSONResponse(
                {
                    "ok": True,
                    "data": {
                        "csrf_token": authenticated.csrf_token,
                        "expires_at": authenticated.expires_at,
                    },
                }
            )
        except AgentRuntimeError as error:
            return _studio_error(error)

    async def detail(request: Request) -> Response:
        try:
            session(request)
            data = service.detail(
                request.path_params["kind"],
                request.path_params["scope"],
                request.path_params.get("name"),
            )
            return JSONResponse({"ok": True, "data": data})
        except AgentRuntimeError as error:
            return _studio_error(error)

    async def preview(request: Request) -> Response:
        try:
            authenticated = session(request, csrf=True)
            data = service.preview(
                await _json_object(request),
                session_token=authenticated.session_token,
            )
            return JSONResponse({"ok": True, "data": data})
        except AgentRuntimeError as error:
            return _studio_error(error)

    async def apply(request: Request) -> Response:
        try:
            authenticated = session(request, csrf=True)
            payload = await _json_object(request)
            preview_id = payload.get("preview_id")
            if not isinstance(preview_id, str):
                raise AgentRuntimeError(
                    ErrorCode.CONFIG_INVALID,
                    "Studio preview_id is required",
                )
            data = service.apply(
                preview_id,
                session_token=authenticated.session_token,
            )
            return JSONResponse({"ok": True, "data": data})
        except AgentRuntimeError as error:
            return _studio_error(error)

    routes = [
        Route("/", index),
        Route("/assets/{name}", asset),
        Route("/api/bootstrap", bootstrap, methods=["POST"]),
        Route("/api/session", current_session),
        Route("/api/studio/catalog", catalog),
        Route(
            "/api/studio/resources/{kind}/{scope}",
            detail,
        ),
        Route(
            "/api/studio/resources/{kind}/{scope}/{name}",
            detail,
        ),
        Route("/api/studio/preview", preview, methods=["POST"]),
        Route("/api/studio/apply", apply, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


class LocalStudioServer:
    """Pre-bound Studio server that can share an MCP process with the dashboard."""

    def __init__(
        self,
        service: StudioService,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
    ) -> None:
        if host != "127.0.0.1":
            raise AgentRuntimeError(
                ErrorCode.CONFIG_INVALID,
                "Studio may bind only to 127.0.0.1",
                details={"host": host},
            )
        self.auth = DashboardAuth(surface_name="Studio")
        self.app = create_studio_app(service, self.auth)
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
        self._owned_task_group: anyio.abc.TaskGroup | None = None
        self._serve_done: anyio.Event | None = None
        self._serve_error: BaseException | None = None
        self._socket_closed = False

    def url(self) -> str:
        return f"http://{self.host}:{self.port}/#token={self.auth.issue_bootstrap_token()}"

    async def _serve(self) -> None:
        try:
            await self._server.serve(sockets=[self._socket])
        except BaseException as error:
            self._serve_error = error
        finally:
            assert self._serve_done is not None
            self._serve_done.set()

    def _close_socket(self) -> None:
        if not self._socket_closed:
            self._socket.close()
            self._socket_closed = True

    async def start(
        self,
        *,
        task_group: anyio.abc.TaskGroup | None = None,
    ) -> None:
        if self._serve_done is not None:
            return
        self._serve_done = anyio.Event()
        active_task_group = task_group
        if active_task_group is None:
            active_task_group = anyio.create_task_group()
            await active_task_group.__aenter__()
            self._owned_task_group = active_task_group
        active_task_group.start_soon(self._serve)
        try:
            with anyio.fail_after(5):
                while not self._server.started:
                    if self._serve_done.is_set():
                        raise AgentRuntimeError(
                            ErrorCode.CAPABILITY_UNAVAILABLE,
                            "Local Studio failed to start",
                            details={
                                "exception_type": (
                                    type(self._serve_error).__name__
                                    if self._serve_error is not None
                                    else "Unknown"
                                )
                            },
                        )
                    await anyio.sleep(0.01)
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        serve_done = self._serve_done
        if serve_done is None:
            self._close_socket()
            return
        self._server.should_exit = True
        await serve_done.wait()
        owned_task_group = self._owned_task_group
        self._owned_task_group = None
        if owned_task_group is not None:
            await owned_task_group.__aexit__(None, None, None)
        self._close_socket()
