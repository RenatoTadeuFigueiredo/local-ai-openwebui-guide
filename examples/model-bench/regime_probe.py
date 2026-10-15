#!/usr/bin/env python3
"""Long-context probe: single huge-prompt turn per config (unique filler each
=> cold prefill for everyone), measuring prefill throughput and decode rate
where KV size and bandwidth actually dominate.

Also: factual sanity QA (same questions all configs, objective string match).
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

STATE = Path.home() / "models/qwen38-omlx/state"
KEY = (STATE / "api-key").read_text().strip()
BASE = "http://127.0.0.1:8084"
UNIT = "com.local.qwen-omlx"
OUT = STATE / "benchmarks"


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def restart_with(kv4=False, ane=False):
    sh(f"launchctl bootout gui/$(id -u)/{UNIT}")
    while sh("pgrep -f secure_server.py").returncode == 0:
        time.sleep(1)
    p = STATE / "model_settings.json"
    data = json.loads(p.read_text())
    prof = data["models"]["qwen38-omlx"]
    prof["turboquant_kv_enabled"] = bool(kv4)
    prof["qwen35_ane_prefill_enabled"] = bool(ane)
    p.write_text(json.dumps(data, indent=1))
    sh(f"launchctl bootstrap gui/$(id -u) ~/.config/local-ai/agents/{UNIT}.plist")
    for _ in range(120):
        try:
            urllib.request.urlopen(BASE + "/health", timeout=2)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("no health")


def ask(payload):
    req = urllib.request.Request(
        BASE + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    r = json.load(urllib.request.urlopen(req, timeout=1800))
    wall = time.perf_counter() - t0
    return r, wall


WORDS = (
    "almanac brigantine compass dowel estuary flotsam galleon harness inkwell "
    "jetty keel lanyard masthead nadir observatory portside quay rigging "
    "sparlock tallywind urchin vantage wharfyard xenolith yawl zenith"
).split()


def big_filler(tag, n_words=10000):
    # fixed coprime step => varied word cycle, identical text across configs;
    # the unique tag sentence at the head kills cross-config cache hits
    body = " ".join(WORDS[(i * 7) % len(WORDS)] for i in range(n_words)) + "."
    return f"In the log tagged {tag}, the entries follow. {body}"


LONG_Q = (
    "\n\nThe ledger above lists ship parts in sequence. "
    "Reply with exactly two sentences: which item appears most often, "
    "and how the list is ordered."
)

QA = [
    ("What is the capital of Australia?", "canberra"),
    ("Chemical symbol for gold?", "au"),
    ("How many continents are there?", "7"),
    ("Year the Berlin Wall fell?", "1989"),
    ("Largest planet in the solar system?", "jupiter"),
    ("Author of Pride and Prejudice?", "austen"),
    ("Speed of light in vacuum (km/s, rounded)?", "300000"),
    ("What gas do plants absorb for photosynthesis?", "carbon dioxide"),
]


def run_long(label, kv4, ane):
    restart_with(kv4, ane)
    # warm tiny request so patches compile, then the big one
    ask(
        {
            "model": "qwen38-omlx",
            "messages": [{"role": "user", "content": "Say OK."}],
            "max_tokens": 8,
            "temperature": 0,
        }
    )
    payload = {
        "model": "qwen38-omlx",
        "messages": [
            {"role": "user", "content": big_filler(label) + LONG_Q}
        ],
        "max_tokens": 256,
        "temperature": 0,
        "reasoning_effort": "medium",
    }
    r, wall = ask(payload)
    u = r["usage"]
    row = {
        "label": label,
        "prompt": u.get("prompt_tokens"),
        "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
        "out": u.get("completion_tokens"),
        "wall_s": round(wall, 2),
        "content_head": (r["choices"][0]["message"].get("content") or "")[:120],
    }
    print(json.dumps(row), flush=True)
    d = OUT / label
    d.mkdir(parents=True, exist_ok=True)
    (d / "longctx.json").write_text(json.dumps(row, indent=1))
    return row


def run_qa(label, kv4, ane):
    # service already running with this config
    score = 0
    details = []
    for q, expect in QA:
        r, _ = ask(
            {
                "model": "qwen38-omlx",
                "messages": [{"role": "user", "content": q}],
                "max_tokens": 512,
                "temperature": 0,
                "reasoning_effort": "low",
            }
        )
        text = (
            (r["choices"][0]["message"].get("content") or "")
            .lower()
        )
        hit = expect.lower() in text
        score += hit
        details.append({"q": q, "expect": expect, "hit": hit})
    d = OUT / label
    d.mkdir(parents=True, exist_ok=True)
    (d / "qa.json").write_text(
        json.dumps({"score": score, "of": len(QA), "details": details}, indent=1)
    )
    print(f"{label}: QA {score}/{len(QA)}", flush=True)


def main():
    import sys

    mode = sys.argv[1]
    label = sys.argv[2]
    kv4 = "--kv4" in sys.argv
    ane = "--ane" in sys.argv
    if mode == "long":
        run_long(label, kv4, ane)
    elif mode == "qa":
        run_qa(label, kv4, ane)


if __name__ == "__main__":
    main()
