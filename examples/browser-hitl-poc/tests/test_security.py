from __future__ import annotations

from browser_hitl import security


def test_portal_cookie_is_bound_to_grant_user_and_epoch(tmp_path, monkeypatch) -> None:
    secret = tmp_path / "portal-key"
    secret.write_text("x" * 64)
    monkeypatch.setenv("BROWSER_HITL_PORTAL_SECRET_FILE", str(secret))

    value = security.portal_cookie_value("grant-a", "user-a", 3, "access-sub-a")
    assert security.verify_portal_cookie(value, "grant-a", "user-a", 3, "access-sub-a")
    assert not security.verify_portal_cookie(value, "grant-b", "user-a", 3, "access-sub-a")
    assert not security.verify_portal_cookie(value, "grant-a", "user-b", 3, "access-sub-a")
    assert not security.verify_portal_cookie(value, "grant-a", "user-a", 4, "access-sub-a")
    assert not security.verify_portal_cookie(value, "grant-a", "user-a", 3, "access-sub-b")


def test_csrf_is_bound_to_grant(tmp_path, monkeypatch) -> None:
    secret = tmp_path / "portal-key"
    secret.write_text("y" * 64)
    monkeypatch.setenv("BROWSER_HITL_PORTAL_SECRET_FILE", str(secret))

    token = security.csrf_token("grant-a")
    assert security.verify_csrf("grant-a", token)
    assert not security.verify_csrf("grant-b", token)
