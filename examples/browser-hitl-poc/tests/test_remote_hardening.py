from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from browser_hitl import security
from browser_hitl.api import enforce_public_surface, is_public_path, require_grant_owner
from browser_hitl.security import AccessIdentity, AccessJWTValidator
from browser_hitl.settings import Settings
from browser_hitl.store import Conflict, Store


def _settings_env(monkeypatch, tmp_path: Path, **overrides: str) -> None:
    values = {
        "BROWSER_HITL_ROOT": str(tmp_path),
        "BROWSER_HITL_PUBLIC_BASE_URL": "https://browser.seudominio.com",
        "BROWSER_HITL_PUBLIC_HOST": "browser.seudominio.com",
        "BROWSER_HITL_ACCESS_REQUIRED": "true",
        "BROWSER_HITL_ACCESS_TEAM_DOMAIN": "https://seudominio.cloudflareaccess.com",
        "BROWSER_HITL_ACCESS_AUDIENCE": "browser-audience",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_remote_settings_fail_closed_without_access(monkeypatch, tmp_path: Path) -> None:
    _settings_env(monkeypatch, tmp_path, BROWSER_HITL_ACCESS_REQUIRED="false")
    with pytest.raises(RuntimeError, match="requires Cloudflare Access"):
        Settings.from_env()


def test_public_host_exposes_only_takeover_portal_and_viewer(monkeypatch) -> None:
    from browser_hitl import api

    remote_settings = Settings(
        **{
            **api.settings.__dict__,
            "public_host": "browser.seudominio.com",
            "public_base_url": "https://browser.seudominio.com",
            "access_required": True,
        }
    )
    monkeypatch.setattr(api, "settings", remote_settings)
    public_headers = {"host": "browser.seudominio.com"}
    for path in (
        "/takeover/token",
        "/takeover/token/redeem",
        "/portal",
        "/portal/complete",
        "/viewer/vnc.html",
        "/viewer/websockify",
    ):
        assert is_public_path(path)
        assert enforce_public_surface(public_headers, path)
    for path in ("/", "/health", "/admin/profiles", "/tool/session/status", "/portal/evil"):
        assert not is_public_path(path)
        with pytest.raises(HTTPException) as caught:
            enforce_public_surface(public_headers, path)
        assert caught.value.status_code == 404


def test_store_migrates_and_pins_unique_access_email(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    with sqlite3.connect(database) as con:
        con.executescript(
            """
            CREATE TABLE profiles (
              user_id TEXT PRIMARY KEY, profile_id TEXT UNIQUE, display_name TEXT,
              runtime_slot INTEGER UNIQUE, enabled INTEGER, created_at INTEGER, updated_at INTEGER
            );
            CREATE TABLE sessions (
              session_id TEXT PRIMARY KEY, user_id TEXT, profile_id TEXT UNIQUE, state TEXT,
              epoch INTEGER, chat_id TEXT, current_url TEXT, runtime_slot INTEGER,
              created_at INTEGER, updated_at INTEGER, last_heartbeat_at INTEGER
            );
            CREATE TABLE grants (
              grant_id TEXT PRIMARY KEY, token_hash TEXT UNIQUE, session_id TEXT,
              user_id TEXT, epoch INTEGER, status TEXT, created_at INTEGER,
              expires_at INTEGER, redeemed_at INTEGER, completed_at INTEGER
            );
            INSERT INTO profiles VALUES ('legacy','profile-legacy','Legacy',0,1,1,1);
            """
        )
    store = Store(database, tmp_path / "audit.jsonl")
    store.initialize()
    store.initialize()
    with sqlite3.connect(database) as con:
        profile_columns = {row[1] for row in con.execute("PRAGMA table_info(profiles)")}
        grant_columns = {row[1] for row in con.execute("PRAGMA table_info(grants)")}
        assert "access_email" in profile_columns
        assert "owner_email" in grant_columns
        assert con.execute("SELECT access_email FROM profiles WHERE user_id='legacy'").fetchone()[0] is None
    first = store.provision_profile("user-a", "A", " Owner@Example.COM ")
    assert first["access_email"] == "owner@example.com"
    with pytest.raises(Conflict, match="already assigned"):
        store.provision_profile("user-b", "B", "owner@example.com")


def test_cross_owner_identity_is_concealed() -> None:
    grant = {"owner_email": "owner@example.com"}
    require_grant_owner(grant, AccessIdentity(email="owner@example.com", subject="owner-sub", expires_at=999_999_999_999))
    with pytest.raises(HTTPException) as caught:
        require_grant_owner(grant, AccessIdentity(email="other@example.com", subject="other-sub", expires_at=999_999_999_999))
    assert caught.value.status_code == 404


def test_access_jwt_validator_pins_signature_issuer_audience_and_claims(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    now = dt.datetime.now(dt.UTC)
    claims = {
        "iss": "https://seudominio.cloudflareaccess.com",
        "aud": ["browser-audience"],
        "sub": "access-subject",
        "email": "Owner@Example.COM",
        "type": "app",
        "iat": now,
        "nbf": now - dt.timedelta(seconds=1),
        "exp": now + dt.timedelta(minutes=5),
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})
    validator = AccessJWTValidator("https://seudominio.cloudflareaccess.com", "browser-audience")

    class Key:
        key = public_key

    monkeypatch.setattr(validator._client, "get_signing_key_from_jwt", lambda _token: Key())
    identity = validator.validate(token)
    assert identity == AccessIdentity(email="owner@example.com", subject="access-subject", expires_at=int(claims["exp"].timestamp()))

    for changed in (
        {"aud": ["chat-audience"]},
        {"iss": "https://evil.cloudflareaccess.com"},
        {"email": None},
        {"nbf": now + dt.timedelta(minutes=10)},
        {"exp": now - dt.timedelta(seconds=1)},
    ):
        bad = jwt.encode({**claims, **changed}, private_key, algorithm="RS256", headers={"kid": "test-key"})
        with pytest.raises(HTTPException) as caught:
            validator.validate(bad)
        assert caught.value.status_code == 403


def test_https_cookie_is_bound_to_access_subject(tmp_path, monkeypatch) -> None:
    secret = tmp_path / "portal-key"
    secret.write_text("s" * 64)
    monkeypatch.setenv("BROWSER_HITL_PORTAL_SECRET_FILE", str(secret))
    monkeypatch.setenv("BROWSER_HITL_PUBLIC_BASE_URL", "https://browser.seudominio.com")
    assert security.portal_cookie_name() == "__Host-browser_hitl"
    value = security.portal_cookie_value("grant", "user", 2, "subject-a")
    claims = security.portal_cookie_claims(value)
    assert claims and claims.grant_id == "grant" and claims.access_subject == "subject-a"
    assert security.verify_portal_cookie(value, "grant", "user", 2, "subject-a")
    assert not security.verify_portal_cookie(value, "grant", "user", 2, "subject-b")
