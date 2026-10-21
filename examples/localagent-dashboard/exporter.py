#!/usr/bin/env python3
"""Prometheus exporter for the local oMLX profile.

Scrapes the running facade (health + cumulative stats) and the server log,
and republishes them as text/plain metrics for the local Prometheus.

The exporter is read-only: it never signals the server, never rotates the log,
and keeps its byte offset in ``state/monitoring/exporter-offset`` so a restart
does not double count.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
LOG = STATE / "launcher.log"
OFFSET_FILE = STATE / "monitoring" / "exporter-offset"
BIND = ("127.0.0.1", 8791)

FINISH_RE = re.compile(
    r"(?:Chat completion|Completion): model=(\S+), (\d+) tokens in ([\d.]+)s "
    r"\(([\d.]+) tok/s\), prompt: (\d+).*?finish_reason=(\w+)"
    r"(?:.*stream_model_ttft=([\d.]+)s)?"
)
PRIMED_RE = re.compile(r"MTP path activated for uid=\d+ \(.*primed=(\d+)\)")
ACCEPT_RE = re.compile(r"accept=(\d+)/(\d+)")
PARK_RE = re.compile(r"MTP\[[^\]]+\] parked for (\d+) standard tokens")
REENTRY_RE = re.compile(r"MTP\[[^\]]+\] re-entry probe succeeded")
RESTORE_RE = re.compile(r"Prefix cache restore")
ERR_RES = {
    "handoff": re.compile(r"handoff (?:raised|failed)"),
    "engine": re.compile(r"Engine loop error"),
    "memory_guard": re.compile(r"memory guard aborted|prefill memory guard rejected"),
    "stream": re.compile(r"Error during chat streaming"),
}

COUNTERS: dict[str, float] = {}
PER_MODEL: dict[str, dict[str, float]] = {}


def _bump(name: str, value: float = 1.0) -> None:
    COUNTERS[name] = COUNTERS.get(name, 0.0) + value


def _prom_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def read_log() -> None:
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    offset = int(OFFSET_FILE.read_text()) if OFFSET_FILE.exists() else 0
    if not LOG.exists():
        return
    size = LOG.stat().st_size
    if size < offset:  # rotated or truncated: counters restart with the file
        offset = 0
        COUNTERS.clear()
        for entry in PER_MODEL.values():
            for field in ("logged_prompt", "logged_completion", "logged_requests",
                          "ttft_sum", "ttft_count"):
                entry[field] = 0.0
    with LOG.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read()
        new_offset = handle.tell()
    if not chunk:
        return
    text = chunk.decode("utf-8", "replace")
    for line in text.splitlines():
        if ACCEPT_RE.search(line) and "finish=" in line:
            match = ACCEPT_RE.search(line)
            _bump("mtp_accept", int(match.group(1)))
            _bump("mtp_draft", int(match.group(2)))
        done = FINISH_RE.search(line)
        if done:
            entry = _entry(done.group(1))
            entry["logged_completion"] += float(done.group(2))
            entry["logged_prompt"] += float(done.group(5))
            entry["logged_requests"] += 1
            _bump(f"finish_{done.group(6)}")
            if done.group(7):
                entry["ttft_sum"] += float(done.group(7))
                entry["ttft_count"] += 1
        priming = PRIMED_RE.search(line)
        if priming:
            _bump("prefilled_tokens", int(priming.group(1)))
        if PARK_RE.search(line):
            _bump("mtp_parks", int(PARK_RE.search(line).group(1)))
            _bump("mtp_parks_events")
        if REENTRY_RE.search(line):
            _bump("mtp_reentry_success")
        if RESTORE_RE.search(line):
            _bump("cache_restores")
        for kind, pattern in ERR_RES.items():
            if pattern.search(line):
                _bump(f"errors_{kind}")
    OFFSET_FILE.write_text(str(new_offset))


def _entry(model: str) -> dict[str, float]:
    return PER_MODEL.setdefault(
        model,
        {"prompt": 0.0, "completion": 0.0, "cached": 0.0, "requests": 0.0,
         "prefill_s": 0.0, "generation_s": 0.0, "logged_prompt": 0.0,
         "logged_completion": 0.0, "logged_requests": 0.0, "ttft_sum": 0.0,
         "ttft_count": 0.0},
    )


def read_stats() -> None:
    try:
        payload = json.loads((STATE / "stats.json").read_text())
    except (OSError, json.JSONDecodeError):
        return
    for model, row in (payload.get("per_model") or {}).items():
        entry = _entry(model)
        entry["prompt"] = float(row.get("prompt_tokens", 0))
        entry["completion"] = float(row.get("completion_tokens", 0))
        entry["cached"] = float(row.get("cached_tokens", 0))
        entry["requests"] = float(row.get("requests", 0))
        entry["prefill_s"] = float(row.get("prefill_duration", 0))
        entry["generation_s"] = float(row.get("generation_duration", 0))


def read_health() -> dict[str, object]:
    header = (STATE / "auth-header").read_text().strip()
    bearer = header.split(":", 1)[1].strip()
    request = urllib.request.Request(
        "http://127.0.0.1:8084/health",
        headers={"Authorization": f"Bearer {bearer}"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def read_rss() -> float:
    try:
        pid = int((STATE / "server.pid").read_text().strip())
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return float(out.split()[0]) * 1024 if out else 0.0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def hourly_rows() -> list[tuple[int, str, int, int, int]]:
    try:
        with sqlite3.connect(f"file:{STATE / 'usage.sqlite3'}?mode=ro", uri=True) as db:
            return list(db.execute(
                "SELECT timestamp_hour, model_id, requests, completion_tokens, "
                "cached_tokens FROM model_usage_hourly "
                "ORDER BY timestamp_hour DESC LIMIT 48"
            ))
    except sqlite3.Error:
        return []


def render() -> str:
    read_log()
    read_stats()
    lines: list[str] = []
    add = lines.append
    declared: set[str] = set()

    def family(name: str, kind: str, help_text: str) -> None:
        if name in declared:
            return
        declared.add(name)
        add(f"# HELP {name} {help_text}")
        add(f"# TYPE {name} {kind}")

    add("# HELP omlx_healthy Facade answered the health probe.")
    add("# TYPE omlx_healthy gauge")
    declared.add("omlx_healthy")
    try:
        health = read_health()
        add("omlx_healthy 1")
        pool = health.get("engine_pool") or {}
        family("omlx_engine_memory_bytes", "gauge", "Engine pool memory in use.")
        add(f"omlx_engine_memory_bytes {float(pool.get('current_model_memory', 0))}")
        family("omlx_memory_ceiling_bytes", "gauge", "Engine pool ceiling.")
        add(f"omlx_memory_ceiling_bytes {float(pool.get('final_ceiling', 0))}")
        family("omlx_models_loaded", "gauge", "Models currently resident.")
        add(f"omlx_models_loaded {float(pool.get('loaded_count', 0))}")
    except Exception:
        add("omlx_healthy 0")

    family("omlx_server_rss_bytes", "gauge", "Resident memory of the server process.")
    add(f"omlx_server_rss_bytes {read_rss()}")

    for model, row in PER_MODEL.items():
        label = _prom_escape(model)
        for field, metric, help_text, kind in (
            ("prompt", "omlx_prompt_tokens_total", "Prompt tokens served.", "counter"),
            ("completion", "omlx_completion_tokens_total", "Completion tokens served.", "counter"),
            ("cached", "omlx_cached_tokens_total", "Prompt tokens served from cache.", "counter"),
            ("requests", "omlx_requests_total", "Requests completed.", "counter"),
            ("prefill_s", "omlx_prefill_seconds_total", "Seconds spent in prefill.", "counter"),
            ("generation_s", "omlx_generation_seconds_total", "Seconds spent generating.", "counter"),
        ):
            family(metric, kind, help_text)
            add(f'{metric}{{model="{label}"}} {row[field]}')

        prompt = row["prompt"] or 1.0
        family("omlx_cache_hit_ratio", "gauge", "Cached share of prompt tokens.")
        add(f'omlx_cache_hit_ratio{{model="{label}"}} {row["cached"] / prompt:.4f}')

        # Per-request counters parsed from the completion log lines.
        for field, metric, help_text in (
            ("logged_completion", "omlx_generated_tokens_total", "Completion tokens emitted."),
            ("logged_prompt", "omlx_prompt_tokens_logged_total", "Prompt tokens on finished requests."),
            ("logged_requests", "omlx_finished_requests_total", "Requests that reached a finish reason."),
        ):
            family(metric, "counter", help_text)
            add(f'{metric}{{model="{label}"}} {row[field]}')
        family("omlx_ttft_seconds_sum", "counter", "Sum of time to first token.")
        add(f'omlx_ttft_seconds_sum{{model="{label}"}} {row["ttft_sum"]:.4f}')
        family("omlx_ttft_seconds_count", "counter", "Timed first tokens.")
        add(f'omlx_ttft_seconds_count{{model="{label}"}} {row["ttft_count"]:.0f}')

    # Counters taken straight from the request log, so they move per request
    # instead of waiting for the periodic stats.json flush.
    for name, metric, help_text in (
        ("prefilled_tokens", "omlx_prefilled_tokens_total", "Prompt tokens prefilled by MTP admission."),
    ):
        family(metric, "counter", help_text)
        add(f"{metric} {COUNTERS.get(name, 0.0)}")

    for name, metric in (
        ("mtp_accept", "omlx_mtp_accept_total"),
        ("mtp_draft", "omlx_mtp_draft_total"),
        ("mtp_parks", "omlx_mtp_park_tokens_total"),
        ("mtp_parks_events", "omlx_mtp_parks_total"),
        ("mtp_reentry_success", "omlx_mtp_reentry_success_total"),
        ("cache_restores", "omlx_cache_restores_total"),
        ("errors_handoff", "omlx_errors_total"),
        ("errors_engine", "omlx_errors_total"),
        ("errors_memory_guard", "omlx_errors_total"),
        ("errors_stream", "omlx_errors_total"),
    ):
        value = COUNTERS.get(name, 0.0)
        if metric == "omlx_errors_total":
            family("omlx_errors_total", "counter", "Errors by kind.")
            add(f'omlx_errors_total{{kind="{name.removeprefix("errors_")}"}} {value}')
        else:
            family(metric, "counter", f"Accumulated {name.replace('_', ' ')}.")
            add(f"{metric} {value}")

    accept = COUNTERS.get("mtp_accept", 0.0)
    draft = COUNTERS.get("mtp_draft", 0.0)
    if draft:
        family("omlx_mtp_accept_ratio", "gauge", "Accepted drafts over drafted tokens.")
        add(f"omlx_mtp_accept_ratio {accept / draft:.4f}")

    for key, value in COUNTERS.items():
        if key.startswith("finish_"):
            family("omlx_finish_reason_total", "counter", "Finished requests by reason.")
            add(f'omlx_finish_reason_total{{reason="{key.removeprefix("finish_")}"}} {value}')

    family("omlx_hourly_completion_tokens", "gauge",
           "Completion tokens in the recorded hour bucket.")
    family("omlx_hourly_requests", "gauge", "Requests in the recorded hour bucket.")
    for hour, model, requests, completion, _cached in hourly_rows():
        label = _prom_escape(model)
        add(f'omlx_hourly_completion_tokens{{model="{label}",hour="{hour}"}} {completion}')
        add(f'omlx_hourly_requests{{model="{label}",hour="{hour}"}} {requests}')

    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            body = render().encode()
        except Exception as exc:  # keep the scrape alive on parser bugs
            body = f"# exporter error: {exc}\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        pass


if __name__ == "__main__":
    os.makedirs(STATE / "monitoring", exist_ok=True)
    print(f"exporter on http://{BIND[0]}:{BIND[1]}/metrics", flush=True)
    ThreadingHTTPServer(BIND, Handler).serve_forever()
