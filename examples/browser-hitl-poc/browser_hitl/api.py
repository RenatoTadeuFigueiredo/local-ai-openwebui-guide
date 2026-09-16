from __future__ import annotations

import asyncio
import hmac
import html
import http.client
import ipaddress
import time
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote, urlsplit

import uvicorn
import websockets
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, HttpUrl
from starlette.websockets import WebSocket, WebSocketDisconnect

from .runtime import RuntimeManager
from .security import (
    AccessIdentity,
    AccessJWTValidator,
    Caller,
    csrf_token,
    exact_origin,
    portal_cookie_claims,
    portal_cookie_name,
    portal_cookie_value,
    require_admin,
    require_local_client,
    require_tool_caller,
    verify_csrf,
    verify_portal_cookie,
)
from .settings import Settings
from .store import (
    HUMAN_ACTIVE,
    READY_TO_RESUME,
    Conflict,
    Forbidden,
    Locked,
    NotFound,
    Store,
)


class OpenSessionRequest(BaseModel):
    url: HttpUrl
    chat_id: str | None = Field(default=None, max_length=128)


class SessionAction(BaseModel):
    session_id: str
    epoch: int = Field(ge=1)


class NavigateRequest(SessionAction):
    url: HttpUrl


class ClickRequest(SessionAction):
    selector: str = Field(min_length=1, max_length=512)


class TypeRequest(SessionAction):
    selector: str = Field(min_length=1, max_length=512)
    text: str = Field(max_length=8000)
    submit: bool = False


class TakeoverRequest(SessionAction):
    pass


class ResumeRequest(BaseModel):
    session_id: str


class ProvisionRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=160)
    access_email: str = Field(min_length=3, max_length=254)


settings = Settings.from_env()
settings.ensure_dirs()
store = Store(settings.state_db, settings.audit_log)
store.initialize()
runtime = RuntimeManager(settings, store)
access_validator = (
    AccessJWTValidator(settings.access_team_domain, settings.access_audience)
    if settings.access_required
    else None
)
MAX_VIEWER_WEBSOCKET_MESSAGE_BYTES = 16 * 1024 * 1024
active_viewer_websockets: dict[str, WebSocket] = {}
active_viewer_websockets_lock = asyncio.Lock()
@asynccontextmanager
async def lifespan(_app: FastAPI):
    # A restart never silently restores agent control after a human handoff.
    store.recover_fail_closed()
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(
    title="Open WebUI Browser HITL POC",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


def referrer_policy(path: str) -> str:
    # Portal forms need an origin-only Referer fallback because Chromium can
    # serialize the Origin header as "null" under no-referrer. Sending only the
    # origin keeps exact-origin CSRF validation usable without disclosing the
    # one-time takeover token from the URL path.
    return "origin" if is_public_path(path) else "no-referrer"


def request_host(headers: Any) -> str:
    raw = (headers.get("host") or "").strip().casefold()
    if raw.startswith("["):
        return raw.split("]", 1)[0] + "]"
    return raw.split(":", 1)[0]


def is_public_request(headers: Any) -> bool:
    return request_host(headers) == settings.public_host and settings.remote_portal


def is_public_path(path: str) -> bool:
    return (
        path.startswith("/takeover/")
        or path in {"/portal", "/portal/complete"}
        or path.startswith("/viewer/")
    )


def enforce_public_surface(headers: Any, path: str) -> bool:
    public = is_public_request(headers)
    if public and not is_public_path(path):
        raise HTTPException(status_code=404, detail="Not found")
    return public


def require_access_identity(headers: Any) -> AccessIdentity:
    if not settings.access_required or access_validator is None:
        return AccessIdentity(
            email="local@localhost",
            subject="local",
            expires_at=int(time.time()) + settings.human_control_ttl_seconds,
        )
    return access_validator.validate(headers.get("cf-access-jwt-assertion"))


def require_grant_owner(grant: dict[str, Any], identity: AccessIdentity) -> None:
    if not hmac.compare_digest(str(grant.get("owner_email") or ""), identity.email):
        raise HTTPException(status_code=404, detail="Takeover link is invalid or expired")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    require_local_client(request)
    public = is_public_request(request.headers)
    if public and not is_public_path(request.url.path):
        response = JSONResponse(status_code=404, content={"detail": "Not found"})
    else:
        response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = referrer_policy(request.url.path)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = (
        "SAMEORIGIN" if request.url.path.startswith("/viewer/") else "DENY"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if public:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; frame-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
        if request.url.path.startswith("/viewer/")
        else
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; frame-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


@app.exception_handler(NotFound)
async def not_found_handler(_request: Request, error: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(Forbidden)
async def forbidden_handler(_request: Request, error: Forbidden):
    return JSONResponse(status_code=403, content={"detail": str(error)})


@app.exception_handler(Locked)
async def locked_handler(_request: Request, error: Locked):
    return JSONResponse(status_code=423, content={"detail": str(error), "state": HUMAN_ACTIVE})


@app.exception_handler(Conflict)
async def conflict_handler(_request: Request, error: Conflict):
    return JSONResponse(status_code=409, content={"detail": str(error)})


def validate_navigation_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Only absolute HTTP(S) URLs are allowed")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "host.docker.internal"} or host.endswith(".localhost") or host.endswith(".local"):
        raise HTTPException(status_code=403, detail="Private and host-local destinations are blocked")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return value
    if not address.is_global:
        raise HTTPException(status_code=403, detail="Private and host-local destinations are blocked")
    return value


def viewer_request_headers(headers: Any) -> dict[str, str]:
    # noVNC assets need only basic content negotiation. Never forward Access
    # JWTs, cookies, authorization, or proxy/client metadata to websockify.
    allowed = {"accept", "accept-encoding", "accept-language", "user-agent", "range"}
    return {key: value for key, value in headers.items() if key.lower() in allowed}


def viewer_response_headers(headers: list[tuple[str, str]]) -> dict[str, str]:
    # Do not let the internal noVNC server set public-domain cookies, redirects,
    # authentication challenges, framing policy, or disclose server metadata.
    allowed = {
        "accept-ranges",
        "content-encoding",
        "content-range",
        "content-type",
        "etag",
        "last-modified",
        "vary",
    }
    return {key: value for key, value in headers if key.lower() in allowed}


def safe_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": session["session_id"],
        "state": session["state"],
        "epoch": session["epoch"],
        "current_url": session.get("current_url"),
        "chat_id": session.get("chat_id"),
        "updated_at": session["updated_at"],
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "version": "0.1.0", "mode": "local-poc"}


@app.post("/admin/profiles")
async def provision_profile(
    provision: ProvisionRequest,
    _admin: None = Depends(require_admin),
) -> dict[str, Any]:
    profile = store.provision_profile(
        provision.user_id,
        provision.display_name,
        provision.access_email,
    )
    for session_id in profile.pop("_revoked_session_ids", []):
        runtime.cancel_takeover_expiry(str(session_id))
        await close_active_viewer_websocket(
            str(session_id),
            4401,
            "Access identity changed",
        )
        await runtime.stop_viewer(str(session_id))
    profile_dir = settings.profiles_dir / str(profile["profile_id"])
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.chmod(0o700)
    return {
        "user_id": profile["user_id"],
        "profile_id": profile["profile_id"],
        "display_name": profile["display_name"],
        "access_email": profile["access_email"],
        "runtime_slot": profile["runtime_slot"],
        "enabled": bool(profile["enabled"]),
    }


@app.post("/admin/recovery/abort-pending")
async def abort_pending(_admin: None = Depends(require_admin)) -> dict[str, Any]:
    session_ids = [
        str(session["session_id"]) for session in store.active_takeover_sessions()
    ]
    await asyncio.gather(
        *(
            close_active_viewer_websocket(
                session_id,
                4401,
                "Takeover revoked by operator",
            )
            for session_id in session_ids
        )
    )
    return {"aborted": await runtime.abort_active_takeovers()}


@app.get("/admin/profiles")
async def profiles(_admin: None = Depends(require_admin)) -> dict[str, Any]:
    return {
        "profiles": [
            {
                "user_id": item["user_id"],
                "profile_id": item["profile_id"],
                "display_name": item["display_name"],
                "access_email": item["access_email"],
                "runtime_slot": item["runtime_slot"],
                "enabled": bool(item["enabled"]),
            }
            for item in store.list_profiles()
        ]
    }


@app.post("/tool/session/open")
async def open_session(
    request: OpenSessionRequest,
    caller: Caller = Depends(require_tool_caller),
) -> dict[str, Any]:
    profile = store.profile(caller.user_id)
    session = store.create_or_resume_session(
        caller.user_id,
        request.chat_id,
        validate_navigation_url(str(request.url)),
        int(profile["runtime_slot"]),
    )
    await runtime.ensure(session)
    if session["state"] == READY_TO_RESUME:
        return {
            **safe_session(session),
            "instruction": "Human control ended. Call browser_resume before any further browser action.",
        }
    return safe_session(session)


@app.get("/tool/session/status")
async def session_status(caller: Caller = Depends(require_tool_caller)) -> dict[str, Any]:
    return safe_session(store.active_session_for_user(caller.user_id))


@app.post("/tool/session/resume")
async def resume_session(
    request: ResumeRequest,
    caller: Caller = Depends(require_tool_caller),
) -> dict[str, Any]:
    session = await runtime.resume_agent(request.session_id, caller.user_id)
    return safe_session(session)


@app.post("/tool/browser/navigate")
async def browser_navigate(
    request: NavigateRequest,
    caller: Caller = Depends(require_tool_caller),
) -> dict[str, Any]:
    session = store.assert_agent(request.session_id, caller.user_id, request.epoch)
    return await runtime.navigate(session, validate_navigation_url(str(request.url)))


@app.post("/tool/browser/snapshot")
async def browser_snapshot(
    request: SessionAction,
    caller: Caller = Depends(require_tool_caller),
) -> dict[str, Any]:
    session = store.assert_agent(request.session_id, caller.user_id, request.epoch)
    return await runtime.snapshot(session)


@app.post("/tool/browser/click")
async def browser_click(
    request: ClickRequest,
    caller: Caller = Depends(require_tool_caller),
) -> dict[str, Any]:
    session = store.assert_agent(request.session_id, caller.user_id, request.epoch)
    return await runtime.click(session, request.selector)


@app.post("/tool/browser/type")
async def browser_type(
    request: TypeRequest,
    caller: Caller = Depends(require_tool_caller),
) -> dict[str, Any]:
    session = store.assert_agent(request.session_id, caller.user_id, request.epoch)
    return await runtime.type_text(session, request.selector, request.text, request.submit)


@app.post("/tool/takeover/request")
async def request_takeover(
    request: TakeoverRequest,
    caller: Caller = Depends(require_tool_caller),
) -> dict[str, Any]:
    token, grant, session, _browser = await runtime.begin_takeover(
        request.session_id,
        caller.user_id,
        caller.email,
        request.epoch,
        settings.takeover_ttl_seconds,
    )
    # The public URL is sent only to the authenticated Open WebUI frontend. The
    # origin independently authenticates Cloudflare Access and binds its identity
    # to the grant owner before revealing or redeeming the takeover.
    portal_url = f"{settings.public_base_url}/takeover/{quote(token)}"
    return {
        **safe_session(session),
        "portal_url": portal_url,
        "expires_at": grant["expires_at"],
        "instruction": (
            "Agent control is now blocked. Ask the user to open portal_url, finish the human step, "
            "then call browser_status in a new turn. Never request passwords, MFA codes, or CAPTCHA answers in chat."
        ),
    }


def portal_html(
    token: str | None,
    grant: dict[str, Any],
    session: dict[str, Any],
    *,
    active: bool,
    viewer_password: str | None = None,
) -> str:
    safe_state = html.escape(str(session["state"]))
    safe_target = html.escape(str(session.get("current_url") or "about:blank"))
    safe_token = html.escape(token or "", quote=True)
    safe_csrf = html.escape(csrf_token(str(grant["grant_id"])), quote=True)
    frame = ""
    action = f"""
      <form method="post" action="/takeover/{safe_token}/redeem">
        <input type="hidden" name="csrf" value="{safe_csrf}">
        <button type="submit">Assumir navegador</button>
      </form>
    """
    if active:
        if not viewer_password:
            raise RuntimeError("Active takeover has no viewer credential")
        password_fragment = quote(viewer_password, safe="")
        # noVNC reads secret configuration from the URL fragment, which browsers
        # do not send in HTTP requests or Referer headers. The RFB listener is
        # additionally loopback-only and protected by this one-time portal cookie.
        websocket_path = quote("viewer/websockify", safe="/")
        novnc = (
            "/viewer/vnc.html?autoconnect=1&resize=scale"
            f"&path={websocket_path}#password={password_fragment}"
        )
        frame = f'<iframe src="{html.escape(novnc, quote=True)}" title="Navegador"></iframe>'
        action = f"""
          <form method="post" action="/portal/complete">
            <input type="hidden" name="csrf" value="{safe_csrf}">
            <button type="submit">Concluir e devolver ao agente</button>
          </form>
        """
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Browser HITL</title><style>
:root{{font-family:system-ui,sans-serif;color-scheme:light dark}}body{{margin:0;background:#0f172a;color:#e2e8f0}}
main{{max-width:1300px;margin:auto;padding:20px}}.card{{background:#111827;border:1px solid #334155;border-radius:18px;padding:20px}}
h1{{font-size:1.3rem;margin:0 0 8px}}p{{color:#cbd5e1}}code{{overflow-wrap:anywhere}}button{{background:#22c55e;color:#052e16;border:0;border-radius:10px;padding:12px 18px;font-weight:750;cursor:pointer}}
iframe{{width:100%;height:70vh;border:1px solid #334155;border-radius:12px;background:#000;margin:16px 0}}.warn{{color:#fbbf24}}
</style></head><body><main><section class="card"><h1>Intervenção humana no navegador</h1>
<p>Estado: <strong>{safe_state}</strong></p><p>Site atual: <code>{safe_target}</code></p>
<p class="warn">Digite senha, MFA ou CAPTCHA somente dentro do navegador abaixo. O agente está bloqueado enquanto você controla a sessão.</p>
{frame}{action}</section></main></body></html>"""


@app.get("/takeover/{token}", response_class=HTMLResponse)
async def takeover_portal(request: Request, token: str) -> HTMLResponse:
    identity = require_access_identity(request.headers)
    grant, session = store.grant_by_token(token)
    require_grant_owner(grant, identity)
    return HTMLResponse(portal_html(token, grant, session, active=False))


def active_grant_from_cookie(
    cookie: str | None,
    identity: AccessIdentity,
) -> tuple[dict[str, Any], dict[str, Any]]:
    claims = portal_cookie_claims(cookie)
    if not claims:
        raise HTTPException(status_code=401, detail="Human control session is not authenticated")
    grant, session = store.active_grant(claims.grant_id)
    require_grant_owner(grant, identity)
    if not verify_portal_cookie(
        cookie,
        str(grant["grant_id"]),
        str(grant["user_id"]),
        int(grant["epoch"]),
        identity.subject,
    ):
        raise HTTPException(status_code=401, detail="Human control session is not authenticated")
    return grant, session


@app.get("/portal", response_class=HTMLResponse)
async def active_takeover_portal(request: Request) -> HTMLResponse:
    identity = require_access_identity(request.headers)
    grant, session = active_grant_from_cookie(
        request.cookies.get(portal_cookie_name()),
        identity,
    )
    viewer_password = str((await runtime.viewer(session))["password"])
    return HTMLResponse(
        portal_html(
            None,
            grant,
            session,
            active=True,
            viewer_password=viewer_password,
        )
    )


@app.post("/takeover/{token}/redeem")
async def takeover_redeem(request: Request, token: str, csrf: str = Form(...)):
    identity = require_access_identity(request.headers)
    if not exact_origin(request):
        raise HTTPException(status_code=403, detail="Invalid request origin")
    grant, _session = store.grant_by_token(token)
    require_grant_owner(grant, identity)
    if not verify_csrf(str(grant["grant_id"]), csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    active_expires_at = min(
        identity.expires_at,
        int(time.time()) + settings.human_control_ttl_seconds,
    )
    grant, session = store.redeem_takeover(token, active_expires_at)
    runtime.schedule_takeover_expiry(
        str(grant["grant_id"]),
        str(session["session_id"]),
        active_expires_at,
    )
    response = RedirectResponse("/portal", status_code=303)
    response.set_cookie(
        portal_cookie_name(),
        portal_cookie_value(
            str(grant["grant_id"]),
            str(grant["user_id"]),
            int(grant["epoch"]),
            identity.subject,
        ),
        secure=settings.public_base_url.startswith("https://"),
        httponly=True,
        samesite="strict",
        path="/",
        # Session cookie: the five-minute deadline limits initial redemption,
        # not an already-active human interaction. Completion or fail-closed
        # recovery revokes the server-side grant.
    )
    return response


@app.get("/viewer/{path:path}")
async def viewer_http_proxy(request: Request, path: str):
    identity = require_access_identity(request.headers)
    _grant, session = active_grant_from_cookie(
        request.cookies.get(portal_cookie_name()),
        identity,
    )
    viewer = await runtime.viewer(session)
    target_path = "/" + path
    if path == "vnc.html":
        target_path += "?" + request.url.query
    elif request.url.query:
        target_path += "?" + request.url.query

    def upstream_request() -> tuple[int, list[tuple[str, str]], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", int(viewer["novnc_port"]), timeout=15)
        connection.request(
            "GET",
            target_path,
            headers=viewer_request_headers(request.headers),
        )
        response = connection.getresponse()
        payload = response.read()
        response_headers = viewer_response_headers(response.getheaders())
        status = response.status
        connection.close()
        return status, list(response_headers.items()), payload

    status, headers, payload = await asyncio.to_thread(upstream_request)
    return Response(content=payload, status_code=status, headers=dict(headers))


@app.websocket("/viewer/websockify")
async def viewer_websocket_proxy(websocket: WebSocket):
    try:
        require_local_client(websocket)
        if not enforce_public_surface(websocket.headers, websocket.url.path):
            # Local mode remains available for explicit loopback testing only.
            pass
        identity = require_access_identity(websocket.headers)
        _grant, session = active_grant_from_cookie(
            websocket.cookies.get(portal_cookie_name()),
            identity,
        )
    except (NotFound, HTTPException):
        await websocket.close(code=4401)
        return
    origin = (websocket.headers.get("origin") or "").rstrip("/")
    if origin != settings.public_base_url:
        await websocket.close(code=4403)
        return
    viewer = await runtime.viewer(session)
    active_expires_at = int(_grant.get("active_expires_at") or 0)
    remaining_seconds = active_expires_at - int(time.time())
    if remaining_seconds <= 0:
        await runtime.expire_takeover(str(_grant["grant_id"]), str(session["session_id"]))
        await websocket.close(code=4401)
        return
    requested_protocols = [
        item.strip()
        for item in (websocket.headers.get("sec-websocket-protocol") or "").split(",")
        if item.strip() in {"binary", "base64"}
    ]
    try:
        async with websockets.connect(
            f"ws://127.0.0.1:{viewer['novnc_port']}/websockify",
            subprotocols=requested_protocols or None,
            origin="http://127.0.0.1",
            max_size=MAX_VIEWER_WEBSOCKET_MESSAGE_BYTES,
        ) as upstream:
            session_id = str(session["session_id"])
            async with active_viewer_websockets_lock:
                if session_id in active_viewer_websockets:
                    await websocket.close(code=4429, reason="A viewer is already connected")
                    return
                active_viewer_websockets[session_id] = websocket
            await websocket.accept(subprotocol=upstream.subprotocol)

            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    if message.get("bytes") is not None:
                        if len(message["bytes"]) > MAX_VIEWER_WEBSOCKET_MESSAGE_BYTES:
                            raise ValueError("Viewer WebSocket message is too large")
                        await upstream.send(message["bytes"])
                    elif message.get("text") is not None:
                        if len(message["text"].encode("utf-8")) > MAX_VIEWER_WEBSOCKET_MESSAGE_BYTES:
                            raise ValueError("Viewer WebSocket message is too large")
                        await upstream.send(message["text"])

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            async def expire_deadline() -> None:
                await asyncio.sleep(remaining_seconds)
                try:
                    await websocket.close(code=4408, reason="Human control session expired")
                except RuntimeError:
                    pass

            tasks = [
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
                asyncio.create_task(expire_deadline()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass
    finally:
        session_id = str(session["session_id"])
        async with active_viewer_websockets_lock:
            if active_viewer_websockets.get(session_id) is websocket:
                active_viewer_websockets.pop(session_id, None)


async def close_active_viewer_websocket(session_id: str, code: int, reason: str) -> None:
    async with active_viewer_websockets_lock:
        websocket = active_viewer_websockets.pop(session_id, None)
    if websocket:
        try:
            await websocket.close(code=code, reason=reason)
        except RuntimeError:
            pass


@app.post("/portal/complete")
async def takeover_complete(request: Request, csrf: str = Form(...)):
    identity = require_access_identity(request.headers)
    if not exact_origin(request):
        raise HTTPException(status_code=403, detail="Invalid request origin")
    grant, _session = active_grant_from_cookie(
        request.cookies.get(portal_cookie_name()),
        identity,
    )
    if not verify_csrf(str(grant["grant_id"]), csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    if not verify_portal_cookie(
        request.cookies.get(portal_cookie_name()),
        str(grant["grant_id"]),
        str(grant["user_id"]),
        int(grant["epoch"]),
        identity.subject,
    ):
        raise HTTPException(status_code=401, detail="Human control session is not authenticated")
    await close_active_viewer_websocket(
        str(grant["session_id"]),
        1000,
        "Human control completed",
    )
    _grant, session = await runtime.complete_takeover(
        str(grant["grant_id"]),
        str(grant["session_id"]),
    )
    response = HTMLResponse(
        "<!doctype html><html lang='pt-BR'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        "<body style='font-family:system-ui;padding:2rem'><h1>Controle devolvido</h1>"
        "<p>Volte ao chat e peça para o agente continuar. Ele receberá uma nova lease antes de observar a página.</p></body></html>"
    )
    response.delete_cookie(
        portal_cookie_name(),
        path="/",
        secure=settings.public_base_url.startswith("https://"),
        httponly=True,
        samesite="strict",
    )
    return response


def main() -> None:
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
