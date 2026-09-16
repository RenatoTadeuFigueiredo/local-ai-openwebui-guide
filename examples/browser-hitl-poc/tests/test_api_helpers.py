from __future__ import annotations

from browser_hitl.api import (
    portal_html,
    referrer_policy,
    viewer_request_headers,
    viewer_response_headers,
)


def configure_portal_secret(tmp_path, monkeypatch) -> None:
    secret = tmp_path / "portal-key"
    secret.write_text("z" * 64)
    monkeypatch.setenv("BROWSER_HITL_PORTAL_SECRET_FILE", str(secret))


def test_active_portal_supplies_vnc_password_only_in_url_fragment(tmp_path, monkeypatch) -> None:
    configure_portal_secret(tmp_path, monkeypatch)
    html = portal_html(
        None,
        {"grant_id": "grant-a"},
        {"state": "HUMAN_ACTIVE", "current_url": "https://example.com"},
        active=True,
        viewer_password="secret value&more",
    )

    assert (
        "?autoconnect=1&amp;resize=scale&amp;path=viewer/websockify"
        "#password=secret%20value%26more"
    ) in html
    assert "?password=" not in html
    assert "takeover-token" not in html
    assert 'action="/portal/complete"' in html
    assert "Digite senha" in html


def test_waiting_portal_never_contains_viewer_password(tmp_path, monkeypatch) -> None:
    configure_portal_secret(tmp_path, monkeypatch)
    html = portal_html(
        "takeover-token",
        {"grant_id": "grant-a"},
        {"state": "WAITING_FOR_HUMAN", "current_url": "https://example.com"},
        active=False,
    )

    assert "#password=" not in html
    assert "Assumir navegador" in html


def test_portal_referrer_policy_preserves_only_origin_for_csrf_fallback() -> None:
    assert referrer_policy("/takeover/token") == "origin"
    assert referrer_policy("/portal") == "origin"
    assert referrer_policy("/portal/complete") == "origin"
    assert referrer_policy("/viewer/vnc.html") == "origin"
    assert referrer_policy("/health") == "no-referrer"
    assert referrer_policy("/tool/session/status") == "no-referrer"


def test_viewer_header_allowlists_strip_access_and_cookie_material() -> None:
    request_headers = viewer_request_headers(
        {
            "Accept": "text/html",
            "Range": "bytes=0-10",
            "Cf-Access-Jwt-Assertion": "secret-jwt",
            "Cookie": "secret-cookie",
            "Authorization": "secret-auth",
            "X-Forwarded-For": "192.0.2.1",
        }
    )
    assert request_headers == {"Accept": "text/html", "Range": "bytes=0-10"}

    response_headers = viewer_response_headers(
        [
            ("Content-Type", "text/html"),
            ("ETag", '"asset"'),
            ("Set-Cookie", "evil=1"),
            ("Location", "https://evil.example"),
            ("WWW-Authenticate", "Basic"),
            ("Server", "internal"),
        ]
    )
    assert response_headers == {"Content-Type": "text/html", "ETag": '"asset"'}
