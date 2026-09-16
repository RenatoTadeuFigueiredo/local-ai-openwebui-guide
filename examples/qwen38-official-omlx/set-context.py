#!/usr/bin/env python3
"""Transactionally switch the installed profile between native 256K and 32K rollback."""
from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
SETTINGS = STATE / "settings.json"
MODEL_SETTINGS = STATE / "model_settings.json"
MODEL_ID = "qwen38-official-omlx"
ALLOWED = {32_768, 262_144}


def load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def atomic_owner_only(path: Path, payload: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def port_is_open() -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", 8084)) == 0


def launchd_is_loaded() -> bool:
    return subprocess.run(
        [
            "launchctl",
            "print",
            f"gui/{os.getuid()}/com.local.qwen38-official",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def recorded_pid_is_active() -> bool:
    pid_file = STATE / "server.pid"
    try:
        raw = pid_file.read_text(encoding="ascii").strip()
        pid = int(raw)
    except (FileNotFoundError, OSError, UnicodeError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="switch the stopped qwen38-official profile context transactionally"
    )
    parser.add_argument("context", type=int, choices=sorted(ALLOWED))
    args = parser.parse_args()

    if port_is_open():
        raise SystemExit("port 8084 is active; stop/unload the model before changing context")
    if launchd_is_loaded():
        raise SystemExit(
            "LaunchAgent is still loaded; bootout it before changing context"
        )
    if recorded_pid_is_active():
        raise SystemExit(
            "state/server.pid still names a live process; stop and investigate it first"
        )

    originals = {
        SETTINGS: SETTINGS.read_bytes(),
        MODEL_SETTINGS: MODEL_SETTINGS.read_bytes(),
    }
    settings = load_object(SETTINGS)
    model_settings = load_object(MODEL_SETTINGS)
    profile = (model_settings.get("models") or {}).get(MODEL_ID)
    if not isinstance(profile, dict):
        raise SystemExit(f"missing pinned model profile {MODEL_ID!r}")

    sampling = settings.setdefault("sampling", {})
    sampling["max_context_window"] = args.context
    sampling["max_context_window_policy"] = args.context
    profile["max_context_window"] = args.context
    if args.context == 262_144:
        settings.setdefault("cache", {})["ssd_cache_max_size"] = "40GB"

    encoded = {
        SETTINGS: (json.dumps(settings, indent=2, ensure_ascii=False) + "\n").encode(),
        MODEL_SETTINGS: (
            json.dumps(model_settings, indent=2, ensure_ascii=False) + "\n"
        ).encode(),
    }
    try:
        for path, payload in encoded.items():
            atomic_owner_only(path, payload)
        subprocess.run(
            [
                str(ROOT / "runtime/venv/bin/python"),
                str(ROOT / "verify-model.py"),
                "--quick",
            ],
            check=True,
        )
    except BaseException:
        for path, payload in originals.items():
            atomic_owner_only(path, payload)
        print("context change failed; both JSON files were restored", file=sys.stderr)
        raise

    print(f"context set coherently to {args.context}; quick verification passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
