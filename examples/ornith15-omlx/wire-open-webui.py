#!/usr/bin/env python3
"""Register the ornith15-omlx profile in Open WebUI (idempotent).

Adds a third OpenAI-compatible connection (prefix `ornith`), a model row so the
model appears in the picker, and a wildcard read grant so every user sees it.
Run with the Open WebUI service stopped or expect a restart afterwards.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path.home() / "services/open-webui-mac/data/webui.db"
URL = "http://127.0.0.1:8086/v1"
PREFIX = "ornith"
MODEL_ID = "ornith15-omlx"
DISPLAY = "Ornith 1.5 9B oQ4e"
DESCRIPTION = (
    "Ornith-1.5-9B oQ4e mixed 4/5-bit, pinned HF revision f601221, Lightning MTP depth <= 3. "
    "Isolated oMLX profile on 127.0.0.1:8086."
)


def main() -> int:
    api_key = (ROOT / "state/api-key").read_text().strip()
    admin = sqlite3.connect(DB)
    cur = admin.cursor()

    urls = json.loads(cur.execute("select value from config where key='openai.api_base_urls'").fetchone()[0])
    keys = json.loads(cur.execute("select value from config where key='openai.api_keys'").fetchone()[0])
    configs = json.loads(cur.execute("select value from config where key='openai.api_configs'").fetchone()[0])

    if URL not in urls:
        urls.append(URL)
        index = str(len(configs))
        keys.append(api_key)
        configs[index] = {
            "enable": True,
            "auth_type": "bearer",
            "connection_type": "local",
            "prefix_id": PREFIX,
            "model_ids": [MODEL_ID],
            "provider": "openai",
        }
        now = int(time.time())
        for key, value in (
            ("openai.api_base_urls", urls),
            ("openai.api_keys", keys),
            ("openai.api_configs", configs),
        ):
            cur.execute(
                "update config set value=?, updated_at=? where key=?",
                (json.dumps(value), now, key),
            )
        print(f"connection added: {URL} prefix={PREFIX} index={index}")
    else:
        print("connection already present")

    model_uid = f"{PREFIX}.{MODEL_ID}"
    row = cur.execute("select id from model where id=?", (model_uid,)).fetchone()
    if row is None:
        owner = cur.execute("select id from user where role='admin' limit 1").fetchone()[0]
        now = int(time.time())
        cur.execute(
            "insert into model (id, user_id, base_model_id, name, params, meta, updated_at, created_at, is_active)"
            " values (?,?,?,?,?,?,?,?,1)",
            (
                model_uid,
                owner,
                None,
                DISPLAY,
                json.dumps({"compact_token_threshold": 245760}),
                json.dumps({"description": DESCRIPTION, "capabilities": None, "knowledge": None}),
                now,
                now,
            ),
        )
        print(f"model row created: {model_uid}")
    else:
        print("model row already present")

    grant = cur.execute(
        "select id from access_grant where resource_type='model' and resource_id=? and principal_id='*'",
        (model_uid,),
    ).fetchone()
    if grant is None:
        cur.execute(
            "insert into access_grant (id, resource_type, resource_id, principal_type, principal_id, permission, created_at)"
            " values (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), "model", model_uid, "user", "*", "read", int(time.time())),
        )
        print("wildcard read grant created")
    else:
        print("grant already present")

    admin.commit()
    admin.close()
    print("restart Open WebUI to pick up the connection")
    return 0


if __name__ == "__main__":
    sys.exit(main())