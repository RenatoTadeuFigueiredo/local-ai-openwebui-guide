#!/usr/bin/env python3
"""Scaffold the LocalAgent monitoring stack into an oMLX profile.

Usage:
    monitoring/install.py <profile-dir> [--instance NAME] [--base-port N]
                                  [--facade-url URL] [--copy-from DIR]

Copies the stack, picks free ports, writes ``monitoring/.env`` and renders the
Prometheus scrape target. Refuses to overwrite an existing installation.
"""
from __future__ import annotations

import argparse
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ("install.py", "exporter.py", "up.sh", "down.sh", "docker-compose.yml",
         "prometheus", "grafana", "README.md")


def port_free(port: int) -> bool:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick(base: int, taken: set[int]) -> int:
    port = base
    while port in taken or not port_free(port):
        port += 1
    taken.add(port)
    return port


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", type=Path)
    parser.add_argument("--instance")
    parser.add_argument("--base-port", type=int)
    parser.add_argument("--facade-url")
    parser.add_argument("--copy-from", type=Path, default=HERE)
    args = parser.parse_args()

    profile = args.profile.expanduser().resolve()
    if not (profile / "secure_server.py").exists():
        print(f"{profile} does not look like an oMLX profile (no secure_server.py)", file=sys.stderr)
        return 1

    target = profile / "monitoring"
    if (target / ".env").exists():
        print(f"{target}/.env already exists; remove it to reinstall", file=sys.stderr)
        return 1

    taken: set[int] = set()
    base = args.base_port or 8791
    exporter_port = pick(base, taken)
    prom_port = pick(base + 100, taken)
    grafana_port = pick(base + 200, taken)

    target.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        source = args.copy_from / name
        if not source.exists():
            continue
        destination = target / name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        elif destination != source:
            shutil.copy2(source, destination)

    instance = args.instance or profile.name.replace("_", "-").lower()
    facade = args.facade_url
    if not facade:
        candidates = [profile / "qwen-omlx", profile / profile.name, *profile.glob("serve*.sh")]
        match = None
        for candidate in candidates:
            if candidate.exists():
                match = re.search(r"^\s*PORT=(\d+)", candidate.read_text(), re.MULTILINE)
                if match:
                    break
        if not match:
            print("cannot infer the facade port; pass --facade-url", file=sys.stderr)
            return 1
        facade = f"http://127.0.0.1:{match.group(1)}"
    token = subprocess.run(
        ["openssl", "rand", "-hex", "16"], capture_output=True, text=True, check=True
    ).stdout.strip()

    (target / ".env").write_text(
        f"INSTANCE={instance}\n"
        f"GRAFANA_PORT={grafana_port}\n"
        f"PROM_PORT={prom_port}\n"
        f"EXPORTER_PORT={exporter_port}\n"
        f"FACADE_URL={facade}\n"
        f"RENDERER_TOKEN={token}\n"
    )
    (target / "prometheus" / "prometheus.yml").write_text(
        "global:\n  scrape_interval: 15s\n  evaluation_interval: 15s\n\n"
        "scrape_configs:\n  - job_name: omlx\n    static_configs:\n"
        f'      - targets: ["host.docker.internal:{exporter_port}"]\n'
    )
    for script in ("up.sh", "down.sh"):
        path = target / script
        if path.exists():
            path.chmod(0o755)

    print(f"installed in {target}")
    print(f"  facade     {facade}  (fix with FACADE_URL in .env)")
    print(f"  grafana    http://127.0.0.1:{grafana_port}")
    print(f"  prometheus http://127.0.0.1:{prom_port}")
    print(f"  exporter   http://127.0.0.1:{exporter_port}/metrics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
