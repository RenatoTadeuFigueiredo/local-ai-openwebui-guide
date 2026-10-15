#!/usr/bin/env python3
"""Production benchmark suite: one-variable-at-a-time config runs.

Each run:
  1. stops the qwen unit
  2. patches model_settings.json (--kv4 / --ane)
  3. starts the unit, waits for health
  4. runs a 6-turn conversation with a UNIQUE filler prefix per label
     (cold T1 comparable across runs; no cross-run cache contamination)
  5. collects client usage + server-side trace-log metrics + RSS samples
  6. writes state/benchmarks/<label>/{results.json,server-excerpt.log}
  7. stops the unit

All arms share questions and growth pattern; only the config differs.
"""
import argparse
import difflib
import json
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
STATE = HOME / "models/qwen38-omlx/state"
LOG = STATE / "logs/server.log"
BENCH = STATE / "benchmarks"
KEY = (STATE / "api-key").read_text().strip()
BASE = "http://127.0.0.1:8084"
UNIT = "com.local.qwen-omlx"

QUESTIONS = [
    "Summarize the ledger's purpose in two sentences.",
    "Which weather patterns appear most often, and why might that matter?",
    "Draft one recommendation for future keepers based on these notes.",
    "Identify any gaps in the records and propose a fix.",
    "Compare the shipping traffic to a typical modern harbor in three bullets.",
    "Write a single closing paragraph tying all observations together.",
]


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def stop_unit():
    sh(f"launchctl bootout gui/$(id -u)/{UNIT}")
    for _ in range(30):
        if sh("pgrep -fl secure_server.py").returncode != 0:
            return
        time.sleep(1)


def start_unit():
    sh(
        f"launchctl bootstrap gui/$(id -u) ~/.config/local-ai/agents/{UNIT}.plist"
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            urllib.request.urlopen(BASE + "/health", timeout=2)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("service did not become healthy")


def patch_model_settings(kv4=False, ane=False):
    path = STATE / "model_settings.json"
    data = json.loads(path.read_text())
    prof = data["models"]["qwen38-omlx"]
    prof["turboquant_kv_enabled"] = bool(kv4)
    prof["qwen35_ane_prefill_enabled"] = bool(ane)
    path.write_text(json.dumps(data, indent=1))


def api(path, payload=None):
    headers = {"Authorization": f"Bearer {KEY}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    return json.load(urllib.request.urlopen(req, timeout=1800))


class RssSampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.samples = []
        self.stop_flag = threading.Event()

    def run(self):
        while not self.stop_flag.is_set():
            out = sh(
                "ps -o rss= -p $(pgrep -f 'secure_server.py' | head -1) 2>/dev/null"
            ).stdout.strip()
            if out.isdigit():
                self.samples.append(int(out) / 1024 / 1024)  # GiB
            time.sleep(2)


FIN_RE = re.compile(
    r"(\d\d:\d\d:[\d,.]+) .*MTP\[(\d+)\] finish=\w+ tokens=(\d+) cycles=(\d+) "
    r"tok/cycle=[\d.]+ accept=(\d+)/(\d+) \(([\d.]+)%\).*"
    r"timing\[backbone=([\d.]+)ms mtp=([\d.]+)ms sample=([\d.]+)ms cache=([\d.]+)ms\]"
)
ACT_RE = re.compile(
    r"(\d\d:\d\d:[\d,.]+) .*MTP path activated for uid=(\d+) .*primed=(\d+)"
)
TOT_RE = re.compile(
    r"Chat completion: model=\S+, (\d+) tokens in ([\d.]+)s.*prompt: (\d+)"
)
SNAP_RE = re.compile(r"boundary cache snapshot for \S+: storing (\d+)/(\d+) tokens")


def parse_window(raw):
    fins = {m.group(2): m.groups() for m in FIN_RE.finditer(raw)}
    acts = [
        (m.group(1), m.group(2), int(m.group(3))) for m in ACT_RE.finditer(raw)
    ]
    totals = [m.groups() for m in TOT_RE.finditer(raw)]
    snaps = [(int(a), int(b)) for a, b in SNAP_RE.findall(raw)]
    return acts, fins, totals, snaps


def ts_sec(stamp):
    h, m, s = stamp.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--kv4", action="store_true")
    ap.add_argument("--ane", action="store_true")
    ap.add_argument("--effort", default="xhigh")
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument(
        "--shared-filler",
        action="store_true",
        help="use a fixed seed so all runs share the same prompts "
        "(required for output-identity quality checks)",
    )
    args = ap.parse_args()

    out_dir = BENCH / args.label
    out_dir.mkdir(parents=True, exist_ok=True)

    stop_unit()
    patch_model_settings(kv4=args.kv4, ane=args.ane)
    start_unit()

    models = api("/v1/models")
    model_id = models["data"][0]["id"]

    sampler = RssSampler()
    sampler.start()
    offset = LOG.stat().st_size

    # unique filler per label -> cold T1 every run; --shared-filler pins the
    # seed so runs are byte-identical in prompt space (quality A/B mode)
    seed_label = "shared" if args.shared_filler else args.label
    seed = sum(ord(c) for c in seed_label)
    words = (
        "tide gull beacon cargo rope lantern anchor compass harbor vessel "
        "storm chart signal wharf current"
    ).split()
    para = (
        " ".join(words[(seed + i * 7) % len(words)] for i in range(24)) + ". "
    )

    msgs = [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": para * 110 + "\n\n" + QUESTIONS[0]},
    ]

    rows = []
    for turn in range(args.turns):
        payload = {
            "model": model_id,
            "messages": msgs,
            "max_tokens": args.max_tokens,
            "temperature": 0,
            "reasoning_effort": args.effort,
        }
        t0 = time.perf_counter()
        resp = api("/v1/chat/completions", payload)
        wall = time.perf_counter() - t0
        usage = resp["usage"]
        msg_obj = resp["choices"][0]["message"]
        row = {
            "turn": turn + 1,
            "prompt_tokens": usage.get("prompt_tokens"),
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get(
                "cached_tokens", 0
            ),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning_chars": len(msg_obj.get("reasoning_content") or ""),
            "content_chars": len(msg_obj.get("content") or ""),
            "client_wall_s": round(wall, 2),
            "content": msg_obj.get("content") or "",
        }
        rows.append(row)
        print(
            f"[{args.label}] T{row['turn']}: prompt={row['prompt_tokens']} "
            f"cached={row['cached_tokens']} out={row['completion_tokens']} "
            f"wall={wall:.1f}s",
            flush=True,
        )
        if turn < args.turns - 1:
            msgs.append({"role": "assistant", "content": msg_obj.get("content") or ""})
            msgs.append(
                {
                    "role": "user",
                    "content": para * 12 + "\n\n" + QUESTIONS[turn + 1],
                }
            )

    sampler.stop_flag.set()
    sampler.join(timeout=3)

    raw = LOG.read_text(errors="replace")[offset:]
    acts, fins, totals, snaps = parse_window(raw)
    fin_by_uid = {f[1]: f for f in fins.values()}
    act_uids = [uid for _ts, uid, _p in acts][-args.turns :]
    tot_window = totals[-args.turns :]

    for i, row in enumerate(rows):
        if i < len(act_uids):
            uid = act_uids[i]
            primed = next((p for _t, u, p in acts if u == uid), None)
            row["prefilled"] = primed
            f = fin_by_uid.get(uid)
            if f:
                decode_ms = float(f[7]) + float(f[8]) + float(f[9]) + float(f[10])
                row.update(
                    {
                        "decode_s": round(decode_ms / 1000, 2),
                        "decode_tok_s": round(int(f[2]) / max(decode_ms / 1000, 1e-9), 1),
                        "accept_pct": float(f[6]),
                        "cycles": int(f[3]),
                        "backbone_ms": float(f[7]),
                        "mtp_ms": float(f[8]),
                    }
                )
        if i < len(tot_window):
            n_out, t_s, prompt = tot_window[i]
            row["server_total_s"] = float(t_s)
            if "decode_s" in row:
                row["ttft_s"] = round(float(t_s) - row["decode_s"], 2)
                row["prefill_tok_s"] = round(
                    (row["prefilled"] or 0) / max(row["ttft_s"], 1e-9), 1
                )

    results = {
        "label": args.label,
        "config": {
            "turboquant_kv_enabled": bool(args.kv4),
            "qwen35_ane_prefill_enabled": bool(args.ane),
            "effort": args.effort,
            "max_tokens": args.max_tokens,
            "turns": args.turns,
        },
        "rows": rows,
        "snapshots_stored": snaps,
        "rss_gib": {
            "min": round(min(sampler.samples), 2) if sampler.samples else None,
            "max": round(max(sampler.samples), 2) if sampler.samples else None,
            "end": round(sampler.samples[-1], 2) if sampler.samples else None,
        },
    }
    (out_dir / "results.json").write_text(json.dumps(results, indent=1))
    (out_dir / "server-excerpt.log").write_text(raw)

    rates = [r["decode_tok_s"] for r in rows if "decode_tok_s" in r]
    accs = [r["accept_pct"] for r in rows if "accept_pct" in r]
    if not rates:
        raise RuntimeError(
            "no MTP metrics paired — parse window mismatch; "
            f"acts={len(acts)} fins={len(fins)} totals={len(tot_window)}"
        )
    saved = sum(r["cached_tokens"] for r in rows)
    total_prompt = sum(r["prompt_tokens"] for r in rows)
    print(
        f"\n== {args.label} ==\n"
        f"Σ prompt={total_prompt} cached(saved)={saved} "
        f"({saved / max(total_prompt, 1) * 100:.0f}%)\n"
        f"avg decode={sum(rates) / len(rates):.1f} tok/s "
        f"avg accept={sum(accs) / len(accs):.1f}%\n"
        f"RSS min/max/end GiB: {results['rss_gib']}"
    )
    stop_unit()


if __name__ == "__main__":
    main()
