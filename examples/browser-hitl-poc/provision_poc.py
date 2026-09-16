#!/usr/bin/env python3
"""Provision the local browser HITL POC and register its private Open WebUI Tool.

The script is intentionally limited to an explicit allowlist of Open WebUI UUIDs.
Secrets stay in owner-only files and process memory; none are passed in argv.
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import jwt


HOME = Path.home()
WEBUI_ROOT = HOME / "services" / "open-webui-mac"
WEBUI_DB = WEBUI_ROOT / "data" / "webui.db"
WEBUI_SECRET = WEBUI_ROOT / "secrets" / "webui-secret-key"
ROOT = Path(__file__).resolve().parent
SECRETS = ROOT / "secrets"
TOOL_SOURCE = ROOT / "openwebui" / "browser_hitl_tool.py"
BROKER_URL = "http://127.0.0.1:3210"
TOOL_ID = "browser_hitl_private"


def fail(message: str) -> None:
    raise RuntimeError(message)


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


def users() -> list[dict[str, str]]:
    with sqlite3.connect(f"file:{WEBUI_DB}?mode=ro", uri=True) as con:
        rows = con.execute("SELECT id,name,email,role FROM user ORDER BY created_at").fetchall()
    return [{"id": row[0], "name": row[1], "email": row[2], "role": row[3]} for row in rows]


def resolve_users(selectors: list[str]) -> list[dict[str, str]]:
    current = users()
    selected = []
    for selector in selectors:
        exact = [user for user in current if selector in {user["id"], user["email"]}]
        if len(exact) != 1:
            fail(f"Selector did not resolve to exactly one Open WebUI user: {selector}")
        if exact[0]["role"] == "pending":
            fail(f"Pending user cannot receive browser access: {selector}")
        selected.append(exact[0])
    return selected


def short_admin_token() -> str:
    admin = next((user for user in users() if user["role"] == "admin"), None)
    if not admin:
        fail("Open WebUI admin not found")
    now = dt.datetime.now(dt.UTC)
    return jwt.encode(
        {"id": admin["id"], "iat": now, "exp": now + dt.timedelta(minutes=2), "jti": str(uuid.uuid4())},
        WEBUI_SECRET.read_text().strip(),
        algorithm="HS256",
    )


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: object | None = None,
    timeout: int = 60,
) -> tuple[int, Any]:
    request_headers = {"User-Agent": "browser-hitl-poc-provisioner/0.1", **(headers or {})}
    data = None
    if body is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw.decode(errors="replace")[:500]
        return error.code, payload


def ensure_secret(name: str) -> str:
    SECRETS.mkdir(parents=True, exist_ok=True)
    SECRETS.chmod(0o700)
    path = SECRETS / name
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48) + "\n")
    path.chmod(0o600)
    return path.read_text().strip()


def compose_up() -> None:
    rendered = run("docker", "compose", "-f", str(ROOT / "compose.yaml"), "config", check=False)
    if rendered.returncode != 0:
        fail(f"Compose validation failed: {rendered.stderr.strip()}")
    result = run("docker", "compose", "-f", str(ROOT / "compose.yaml"), "up", "-d", "--build", check=False)
    if result.returncode != 0:
        fail(f"Broker startup failed: {result.stderr.strip()}")
    for _ in range(90):
        try:
            status, payload = request_json("GET", BROKER_URL + "/health", timeout=2)
        except (urllib.error.URLError, ConnectionError, http.client.RemoteDisconnected):
            status, payload = 0, None
        if status == 200 and isinstance(payload, dict) and payload.get("ok"):
            return
        import time

        time.sleep(1)
    fail("Broker did not become healthy")


def provision_profiles(selected: list[dict[str, str]], admin_key: str) -> None:
    for user in selected:
        status, _ = request_json(
            "POST",
            BROKER_URL + "/admin/profiles",
            headers={"X-Browser-Admin-Key": admin_key},
            body={
                "user_id": user["id"],
                "display_name": user["name"],
                "access_email": user["email"],
            },
        )
        if status != 200:
            fail(f"Failed to provision browser profile for {user['name']} (HTTP {status})")


def tool_form(selected: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "id": TOOL_ID,
        "name": "Navegador privado com login humano",
        "content": TOOL_SOURCE.read_text(),
        "meta": {
            "description": "Navegador persistente por usuário com takeover humano e lock exclusivo.",
            "manifest": {},
            "has_user_valves": False,
        },
        "access_grants": [
            {"principal_type": "user", "principal_id": user["id"], "permission": "read"}
            for user in selected
        ],
    }


def valve_encryption_enabled() -> bool:
    for raw in (WEBUI_ROOT / "env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "ENABLE_VALVE_ENCRYPTION":
            return value.strip().strip("'\"").lower() == "true"
    return False


def verify_encrypted_tool_valves(tool_key: str) -> None:
    with sqlite3.connect(f"file:{WEBUI_DB}?mode=ro", uri=True) as con:
        row = con.execute("SELECT valves FROM tool WHERE id=?", (TOOL_ID,)).fetchone()
    if not row or not isinstance(row[0], str):
        fail("Open WebUI Tool Valves were not persisted")
    try:
        stored = json.loads(row[0])
    except json.JSONDecodeError:
        stored = row[0]
    if not isinstance(stored, str) or not stored.startswith("gAAAA"):
        fail("Open WebUI Tool Valves are not encrypted at rest")
    for database_file in (WEBUI_DB, WEBUI_DB.with_name("webui.db-wal"), WEBUI_DB.with_name("webui.db-shm")):
        if database_file.exists() and tool_key.encode() in database_file.read_bytes():
            fail(f"Tool credential still appears in {database_file.name}")


def register_tool(selected: list[dict[str, str]], tool_key: str) -> None:
    if not valve_encryption_enabled():
        fail("ENABLE_VALVE_ENCRYPTION=true is required before storing the Tool credential")
    token = short_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    status, existing = request_json("GET", f"http://127.0.0.1:3000/api/v1/tools/id/{TOOL_ID}", headers=headers)
    form = tool_form(selected)
    if status == 404:
        status, _ = request_json("POST", "http://127.0.0.1:3000/api/v1/tools/create", headers=headers, body=form)
    elif status == 200:
        status, _ = request_json(
            "POST",
            f"http://127.0.0.1:3000/api/v1/tools/id/{TOOL_ID}/update",
            headers=headers,
            body=form,
        )
    if status != 200:
        fail(f"Open WebUI Tool registration failed (HTTP {status})")
    status, _ = request_json(
        "POST",
        f"http://127.0.0.1:3000/api/v1/tools/id/{TOOL_ID}/valves/update",
        headers=headers,
        body={"broker_url": BROKER_URL, "tool_api_key": tool_key},
    )
    if status != 200:
        fail(f"Open WebUI Tool valve configuration failed (HTTP {status})")
    verify_encrypted_tool_valves(tool_key)


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--user",
        action="append",
        required=True,
        help="Exact Open WebUI UUID or email; repeat for each approved POC participant.",
    )
    args = parser.parse_args()
    selected = resolve_users(args.user)
    tool_key = ensure_secret("tool-api-key")
    admin_key = ensure_secret("admin-api-key")
    ensure_secret("portal-signing-key")
    compose_up()
    provision_profiles(selected, admin_key)
    register_tool(selected, tool_key)
    print("Browser HITL local POC: PASS")
    print("  broker: http://127.0.0.1:3210")
    print("  Open WebUI Tool: Navegador privado com login humano")
    print("  users:", ", ".join(user["name"] for user in selected))
    print("  public portal:", os.environ.get("BROWSER_HITL_PUBLIC_BASE_URL", "not configured"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
