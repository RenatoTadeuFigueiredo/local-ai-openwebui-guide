from __future__ import annotations

import base64
import hmac
import ipaddress
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError

import jwt
from fastapi import Header, HTTPException, Request


@dataclass(frozen=True)
class Caller:
    user_id: str
    display_name: str
    role: str
    email: str


@dataclass(frozen=True)
class AccessIdentity:
    email: str
    subject: str
    expires_at: int


@dataclass(frozen=True)
class PortalCookie:
    grant_id: str
    user_id: str
    epoch: int
    access_subject: str


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if (
        not email
        or len(email) > 254
        or email.count("@") != 1
        or any(ord(character) < 33 or ord(character) == 127 for character in email)
    ):
        raise ValueError("Invalid email identity")
    local, domain = email.rsplit("@", 1)
    if not local or not domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("Invalid email identity")
    return email


def _read_secret(path_value: str, label: str) -> str:
    path = Path(path_value)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Cannot read {label} secret file") from error
    if len(value) < 32:
        raise RuntimeError(f"{label} secret is too short")
    return value


def tool_secret() -> str:
    path = os.environ.get("BROWSER_HITL_TOOL_SECRET_FILE", "/run/secrets/tool-api-key")
    return _read_secret(path, "tool API")


def admin_secret() -> str:
    path = os.environ.get("BROWSER_HITL_ADMIN_SECRET_FILE", "/run/secrets/admin-api-key")
    return _read_secret(path, "admin API")


def portal_secret() -> str:
    path = os.environ.get("BROWSER_HITL_PORTAL_SECRET_FILE", "/run/secrets/portal-signing-key")
    return _read_secret(path, "portal")


def require_tool_caller(
    x_browser_tool_key: str | None = Header(default=None),
    x_openwebui_user_id: str | None = Header(default=None),
    x_openwebui_user_name: str | None = Header(default=None),
    x_openwebui_user_role: str | None = Header(default=None),
    x_openwebui_user_email: str | None = Header(default=None),
) -> Caller:
    expected = tool_secret()
    if not x_browser_tool_key or not hmac.compare_digest(x_browser_tool_key, expected):
        raise HTTPException(status_code=401, detail="Invalid tool credential")
    if not x_openwebui_user_id or len(x_openwebui_user_id) > 128:
        raise HTTPException(status_code=400, detail="Missing trusted Open WebUI user identity")
    try:
        email = normalize_email(x_openwebui_user_email or "")
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Missing trusted Open WebUI email identity") from error
    return Caller(
        user_id=x_openwebui_user_id,
        display_name=(x_openwebui_user_name or "Open WebUI user")[:160],
        role=(x_openwebui_user_role or "user")[:32],
        email=email,
    )


def require_admin(x_browser_admin_key: str | None = Header(default=None)) -> None:
    expected = admin_secret()
    if not x_browser_admin_key or not hmac.compare_digest(x_browser_admin_key, expected):
        raise HTTPException(status_code=401, detail="Invalid administrator credential")


class AccessJWTValidator:
    """Validate Cloudflare Access application JWTs against the rotating remote JWKS."""

    def __init__(self, team_domain: str, audience: str) -> None:
        self.team_domain = team_domain.rstrip("/")
        self.audience = audience
        self._client = jwt.PyJWKClient(
            f"{self.team_domain}/cdn-cgi/access/certs",
            cache_keys=True,
            max_cached_keys=4,
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
            headers={"User-Agent": "browser-hitl-access-validator/0.2"},
        )

    def validate(self, token: str | None) -> AccessIdentity:
        if not token:
            raise HTTPException(status_code=403, detail="Cloudflare Access identity is required")
        try:
            signing_key = self._client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.team_domain,
                options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "email", "type"]},
            )
            if (
                claims.get("type") != "app"
                or not isinstance(claims["email"], str)
                or not isinstance(claims["sub"], str)
            ):
                raise ValueError("Invalid Access identity claims")
            email = normalize_email(claims["email"])
            subject = claims["sub"].strip()
            if not subject or len(subject) > 512 or any(ord(character) < 32 for character in subject):
                raise ValueError("Invalid Access subject")
        except (jwt.PyJWTError, URLError, OSError, ValueError, KeyError) as error:
            raise HTTPException(status_code=403, detail="Invalid Cloudflare Access identity") from error
        return AccessIdentity(email=email, subject=subject, expires_at=int(claims["exp"]))


def csrf_token(grant_id: str) -> str:
    return hmac.new(portal_secret().encode(), grant_id.encode(), "sha256").hexdigest()


def verify_csrf(grant_id: str, presented: str) -> bool:
    return hmac.compare_digest(csrf_token(grant_id), presented)


def portal_cookie_name() -> str:
    public_base = os.environ.get("BROWSER_HITL_PUBLIC_BASE_URL", "http://127.0.0.1:3210")
    return "__Host-browser_hitl" if public_base.startswith("https://") else "browser_hitl_local"


def _cookie_payload(grant_id: str, user_id: str, epoch: int, access_subject: str) -> str:
    raw = json.dumps(
        [grant_id, user_id, int(epoch), access_subject],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def portal_cookie_value(grant_id: str, user_id: str, epoch: int, access_subject: str) -> str:
    payload = _cookie_payload(grant_id, user_id, epoch, access_subject)
    signature = hmac.new(portal_secret().encode(), payload.encode(), "sha256").hexdigest()
    return f"{payload}.{signature}"


def portal_cookie_claims(value: str | None) -> PortalCookie | None:
    if not value or len(value) > 2048:
        return None
    payload, separator, signature = value.partition(".")
    expected = hmac.new(portal_secret().encode(), payload.encode(), "sha256").hexdigest()
    if not separator or not hmac.compare_digest(signature, expected):
        return None
    try:
        padding = "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload + padding))
        if not isinstance(decoded, list) or len(decoded) != 4:
            return None
        grant_id, user_id, epoch, access_subject = decoded
        if not isinstance(grant_id, str) or not isinstance(user_id, str):
            return None
        if not isinstance(epoch, int) or epoch < 1 or not isinstance(access_subject, str):
            return None
        if not grant_id or not user_id or not access_subject:
            return None
        return PortalCookie(grant_id, user_id, epoch, access_subject)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def verify_portal_cookie(
    value: str | None,
    grant_id: str,
    user_id: str,
    epoch: int,
    access_subject: str,
) -> bool:
    return hmac.compare_digest(
        value or "",
        portal_cookie_value(grant_id, user_id, epoch, access_subject),
    )


def exact_origin(request: Request) -> bool:
    expected = os.environ.get("BROWSER_HITL_PUBLIC_BASE_URL", "http://127.0.0.1:3210").rstrip("/")
    origin = request.headers.get("origin", "").rstrip("/")
    if origin:
        return origin == expected
    referer = request.headers.get("referer", "").rstrip("/")
    return referer == expected or referer.startswith(expected + "/")


def require_local_client(request: Request) -> None:
    host = request.client.host if request.client else ""
    # Docker Desktop and local cloudflared forward through loopback/private
    # interfaces. Public authorization is enforced independently with canonical
    # Host/path checks and a signed Cloudflare Access application JWT.
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise HTTPException(status_code=403, detail="Private broker ingress only") from error
    if not (address.is_loopback or address.is_private):
        raise HTTPException(status_code=403, detail="Private broker ingress only")


def new_nonce() -> str:
    return secrets.token_urlsafe(24)
