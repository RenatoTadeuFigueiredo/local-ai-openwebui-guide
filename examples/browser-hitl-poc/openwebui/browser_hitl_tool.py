"""
title: Navegador HITL privado
author: local
version: 0.1.0
required_open_webui_version: 0.11.0
description: Navegador persistente e isolado por usuário, com takeover humano para login, MFA e CAPTCHA.
"""

from __future__ import annotations

import html
import json
import urllib.error
import urllib.request
from typing import Optional

from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        broker_url: str = Field(
            default="http://127.0.0.1:3210",
            description="Loopback URL of the private browser HITL broker.",
        )
        tool_api_key: str = Field(
            default="",
            description="Private server-side API key. Never expose it in chat.",
            json_schema_extra={"input": {"type": "password"}},
        )

    def __init__(self):
        self.valves = self.Valves()

    def _request(
        self,
        method: str,
        path: str,
        user: dict,
        body: dict | None = None,
    ) -> dict:
        if not self.valves.tool_api_key:
            return {"status": "error", "message": "Browser HITL Tool is not configured by the administrator."}
        base = self.valves.broker_url.rstrip("/")
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "X-Browser-Tool-Key": self.valves.tool_api_key,
            "X-OpenWebUI-User-Id": str(user.get("id") or ""),
            "X-OpenWebUI-User-Name": str(user.get("name") or ""),
            "X-OpenWebUI-User-Role": str(user.get("role") or "user"),
            "X-OpenWebUI-User-Email": str(user.get("email") or ""),
            "Content-Type": "application/json",
            "User-Agent": "openwebui-browser-hitl-tool/0.1",
        }
        request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                payload = json.loads(raw) if raw else {"detail": str(error)}
            except json.JSONDecodeError:
                payload = {"detail": raw.decode(errors="replace")[:500]}
            payload["http_status"] = error.code
            return payload
        except Exception as error:
            return {"status": "error", "message": f"Browser broker unavailable: {error}"}

    async def browser_open(
        self,
        url: str,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__=None,
    ) -> dict:
        """
        Opens or resumes this authenticated Open WebUI user's own persistent browser profile.
        Use this before any other browser action. Never ask the user for passwords, MFA codes,
        passkeys, or CAPTCHA answers in chat; use browser_request_human_control instead.

        :param url: Absolute HTTPS URL to open. Private/localhost destinations are forbidden.
        """
        user = __user__ or {}
        metadata = __metadata__ or {}
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Abrindo navegador privado...", "done": False}})
        result = self._request(
            "POST",
            "/tool/session/open",
            user,
            {"url": url, "chat_id": metadata.get("chat_id")},
        )
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Navegador pronto", "done": True}})
        return result

    async def browser_navigate(
        self,
        session_id: str,
        epoch: int,
        url: str,
        __user__: Optional[dict] = None,
    ) -> dict:
        """
        Navigates the user's active browser while the agent owns the current fenced lease.

        :param session_id: Session ID returned by browser_open.
        :param epoch: Current lease epoch returned by browser_open or browser_resume.
        :param url: Absolute HTTP(S) URL. Private and host-local destinations are blocked.
        """
        return self._request(
            "POST",
            "/tool/browser/navigate",
            __user__ or {},
            {"session_id": session_id, "epoch": epoch, "url": url},
        )

    async def browser_snapshot(
        self,
        session_id: str,
        epoch: int,
        __user__: Optional[dict] = None,
    ) -> dict:
        """
        Reads a bounded text/element snapshot of the current page. This is blocked with HTTP 423
        while human control is pending or active.

        :param session_id: Session ID returned by browser_open.
        :param epoch: Current fenced lease epoch.
        """
        return self._request(
            "POST",
            "/tool/browser/snapshot",
            __user__ or {},
            {"session_id": session_id, "epoch": epoch},
        )

    async def browser_click(
        self,
        session_id: str,
        epoch: int,
        selector: str,
        __user__: Optional[dict] = None,
    ) -> dict:
        """
        Clicks a CSS selector while the agent owns the browser lease. Ask for explicit human
        confirmation before irreversible, financial, sharing, deletion, publishing, or send actions.

        :param session_id: Session ID returned by browser_open.
        :param epoch: Current fenced lease epoch.
        :param selector: CSS selector from browser_snapshot or otherwise verified page structure.
        """
        return self._request(
            "POST",
            "/tool/browser/click",
            __user__ or {},
            {"session_id": session_id, "epoch": epoch, "selector": selector},
        )

    async def browser_type(
        self,
        session_id: str,
        epoch: int,
        selector: str,
        text: str,
        submit: bool = False,
        __user__: Optional[dict] = None,
    ) -> dict:
        """
        Types non-secret text into the browser. Never use this for a password, MFA code, passkey,
        CAPTCHA, recovery code, payment data, or other authentication secret; request human control.

        :param session_id: Session ID returned by browser_open.
        :param epoch: Current fenced lease epoch.
        :param selector: CSS selector of the destination field.
        :param text: Non-secret text to type.
        :param submit: Whether to press Enter afterward. Keep false for consequential actions.
        """
        return self._request(
            "POST",
            "/tool/browser/type",
            __user__ or {},
            {
                "session_id": session_id,
                "epoch": epoch,
                "selector": selector,
                "text": text,
                "submit": submit,
            },
        )

    async def browser_request_human_control(
        self,
        session_id: str,
        epoch: int,
        reason: str = "login, MFA, CAPTCHA, or another human-only step",
        __user__: Optional[dict] = None,
        __event_emitter__=None,
    ) -> dict:
        """
        Pauses all agent input and observation, then creates a short-lived local takeover link for
        the same browser, profile, and tab. Use for login, MFA, CAPTCHA, passkeys, consent, or any
        human-only step. End the current turn after calling this; do not poll indefinitely.

        :param session_id: Session ID returned by browser_open.
        :param epoch: Current fenced lease epoch.
        :param reason: Short non-secret explanation shown to the user. Never include credentials.
        """
        result = self._request(
            "POST",
            "/tool/takeover/request",
            __user__ or {},
            {"session_id": session_id, "epoch": epoch},
        )
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": "Aguardando intervenção humana no navegador",
                        "done": True,
                        "hidden": False,
                    },
                }
            )
        portal_url = str(result.pop("portal_url", ""))
        result["reason"] = reason[:240]
        if not portal_url:
            return result
        safe_reason = html.escape(reason[:240])
        if __event_emitter__:
            # Open WebUI 0.11.0 exposes execute specifically for trusted,
            # transient UI interactions. The panel is created in the main page
            # rather than a sandboxed Rich UI iframe, so its user-activated
            # target=_blank navigation does not inherit iframe sandbox flags.
            # JSON encoding produces JavaScript string literals without eval or
            # interpolation of URL/reason into executable code.
            js_portal_url = json.dumps(portal_url)
            js_reason = json.dumps(reason[:240])
            await __event_emitter__(
                {
                    "type": "execute",
                    "data": {
                        "code": f"""
(() => {{
  const id = 'browser-hitl-takeover-panel';
  document.getElementById(id)?.remove();
  const panel = document.createElement('section');
  panel.id = id;
  panel.dataset.browserHitlTakeover = 'v1';
  panel.style.cssText = 'position:fixed;right:20px;bottom:20px;z-index:2147483646;max-width:420px;padding:18px;border:1px solid #64748b88;border-radius:16px;background:#111827;color:#e5e7eb;box-shadow:0 20px 50px #0008;font-family:system-ui,sans-serif';

  const title = document.createElement('strong');
  title.textContent = 'Intervenção humana necessária';
  title.style.cssText = 'display:block;font-size:16px;margin-bottom:8px';
  const text = document.createElement('p');
  text.textContent = {js_reason};
  text.style.cssText = 'margin:0 0 12px;line-height:1.4';
  const link = document.createElement('a');
  link.href = {js_portal_url};
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = 'Assumir navegador';
  link.style.cssText = 'display:inline-block;padding:11px 16px;border-radius:10px;background:#22c55e;color:#052e16;text-decoration:none;font-weight:750';
  const note = document.createElement('p');
  note.textContent = 'Digite senha, MFA ou CAPTCHA somente no navegador de takeover.';
  note.style.cssText = 'margin:12px 0 0;font-size:13px;opacity:.8';
  const close = document.createElement('button');
  close.type = 'button';
  close.textContent = '×';
  close.setAttribute('aria-label', 'Fechar aviso');
  close.style.cssText = 'position:absolute;right:10px;top:8px;border:0;background:transparent;color:#9ca3af;font-size:22px;cursor:pointer';
  close.addEventListener('click', () => panel.remove());

  panel.append(title, text, link, note, close);
  document.body.appendChild(panel);
}})();
"""
                    },
                }
            )
        component = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{font-family:system-ui,sans-serif;color-scheme:light dark}}body{{margin:0;padding:16px}}
.card{{border:1px solid #64748b55;border-radius:14px;padding:16px;background:#64748b12}}
h3{{margin:0 0 8px}}p{{line-height:1.45}}.note{{font-size:.9rem;opacity:.8}}
</style></head><body><section class="card"><h3>Intervenção humana necessária</h3>
<p>{safe_reason}</p><p>Use o painel verde <strong>Assumir navegador</strong> aberto no canto da tela.</p>
<p class="note">O painel principal evita que a nova aba herde o sandbox desta Rich UI. Não digite credenciais no chat.</p></section>
<script>function h(){{parent.postMessage({{type:'iframe:height',height:document.documentElement.scrollHeight}},'*')}}addEventListener('load',h);new ResizeObserver(h).observe(document.body)</script>
</body></html>"""
        llm_context = {
            key: value for key, value in result.items() if key not in {"expires_at"}
        }
        llm_context["status"] = "WAITING_FOR_HUMAN"
        llm_context["instruction"] = (
            "A private takeover control is visible only to the authenticated user. End this turn. "
            "Never ask for credentials. In a later turn call browser_status, then browser_resume only if READY_TO_RESUME."
        )
        return HTMLResponse(content=component, headers={"Content-Disposition": "inline"}), llm_context

    async def browser_status(self, __user__: Optional[dict] = None) -> dict:
        """
        Returns this Open WebUI user's own active browser state. Call in a new turn after the user
        says they completed the human step. It never accepts another user's identity as input.
        """
        return self._request("GET", "/tool/session/status", __user__ or {})

    async def browser_resume(
        self,
        session_id: str,
        __user__: Optional[dict] = None,
    ) -> dict:
        """
        Obtains a new fenced agent lease only after the human explicitly returned control and the
        session reports READY_TO_RESUME. Never resume merely because the viewer disconnected.

        :param session_id: Session ID returned by browser_open or browser_status.
        """
        return self._request(
            "POST",
            "/tool/session/resume",
            __user__ or {},
            {"session_id": session_id},
        )
