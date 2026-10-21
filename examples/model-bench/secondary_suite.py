#!/usr/bin/env python3
"""Secondary-model suite: one-variable-at-a-time arms for a non-default model.

Adapted from ``bench_suite.py`` (doc 07). Differences: the model is selectable,
the arm axes are engine path (vlm/llm) and MTP on/off instead of KV/ANE, and the
MTP log regex tolerates the 0.7.2 line format.

Each run:
  1. stops the service
  2. patches model_settings.json for the selected model (engine, MTP)
  3. starts the service, waits for health
  4. runs a 6-turn conversation with a UNIQUE filler prefix per label
  5. collects client usage + server-side metrics + RSS samples
  6. writes state/benchmarks/<label>/{results.json,server-excerpt.log}
"""
import argparse
import json
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

STATE = Path.home() / "models/qwen38-omlx/state"
LOG = STATE / "logs/server.log"
BENCH = STATE / "benchmarks"
KEY = (STATE / "api-key").read_text().strip()
BASE = "http://127.0.0.1:8084"
LAUNCHER = Path.home() / "models/qwen38-omlx/qwen-omlx"

QUESTIONS = [
    "Summarize the ledger's purpose in two sentences.",
    "Which weather patterns appear most often, and why might that matter?",
    "Draft one recommendation for future keepers based on these notes.",
    "Identify any gaps in the records and propose a fix.",
    "Compare the shipping traffic to a typical modern harbor in three bullets.",
    "Write a single closing paragraph tying all observations together.",
]

QA = [
    ("What is 17*23? Answer with the number only.", "391"),
    ("Which HTTP status means 'Too Many Requests'? Number only.", "429"),
    ("In Python, which builtin returns the number of items in a list?", "len"),
    ("What does the acronym TLS expand to?", "transport layer security"),
    ("Which git command creates a new branch and switches to it?", "checkout -b"),
    ("What is the time complexity of binary search on a sorted array?", "log"),
    ("Which SQL clause filters groups after aggregation?", "having"),
    ("What is 2**10? Number only.", "1024"),
]


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def stop_unit():
    sh(f"'{LAUNCHER}' stop")
    for _ in range(30):
        if sh("pgrep -fl secure_server.py").returncode != 0:
            break
        time.sleep(1)
    for _ in range(20):
        if sh("lsof -tiTCP:8084 -sTCP:LISTEN").stdout.strip() == "":
            return
        time.sleep(0.5)


def start_unit():
    # The previous stop can leave the listener bound for a moment; retry.
    for attempt in range(3):
        out = sh(f"'{LAUNCHER}' start")
        if "already in use" not in out.stderr + out.stdout:
            break
        time.sleep(4)
    deadline = time.time() + 240
    while time.time() < deadline:
        try:
            urllib.request.urlopen(BASE + "/health", timeout=2)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"service did not become healthy: {out.stdout[-400:]}")


def patch_settings(model, engine, mtp):
    path = STATE / "model_settings.json"
    data = json.loads(path.read_text())
    prof = data["models"][model]
    prof["model_type_override"] = engine
    prof["mtp_enabled"] = mtp == "on"
    path.write_text(json.dumps(data, indent=4) + "\n")


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
                self.samples.append(int(out) / 1024 / 1024)
            time.sleep(2)


FIN_RE = re.compile(
    r"MTP\[(\d+)\] finish=\w+ tokens=(\d+) cycles=(\d+) tok/cycle=[\d.]+ "
    r"accept=(\d+)/(\d+) \(([\d.]+)%\).*?"
    r"timing\[backbone=([\d.]+)ms mtp=([\d.]+)ms sample=([\d.]+)ms cache=([\d.]+)ms\]"
)
ACT_RE = re.compile(r"MTP path activated for uid=(\d+) .*primed=(\d+)")
TOT_RE = re.compile(r"Chat completion: model=\S+, (\d+) tokens in ([\d.]+)s.*prompt: (\d+)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--model", default="sage-a15-omlx")
    ap.add_argument("--engine", choices=("vlm", "llm"), default="vlm")
    ap.add_argument("--mtp", choices=("on", "off"), default="on")
    ap.add_argument("--thinking", choices=("on", "off"), default="off")
    ap.add_argument("--mode", choices=("chat", "qa"), default="chat")
    ap.add_argument("--regime", choices=("short", "long"), default="short")
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--shared-filler", action="store_true")
    args = ap.parse_args()

    out_dir = BENCH / args.label
    out_dir.mkdir(parents=True, exist_ok=True)

    stop_unit()
    patch_settings(args.model, args.engine, args.mtp)
    start_unit()

    sampler = RssSampler()
    sampler.start()
    offset = LOG.stat().st_size

    seed_label = "shared" if args.shared_filler else args.label
    seed = sum(ord(c) for c in seed_label)
    words = (
        "tide gull beacon cargo rope lantern anchor compass harbor vessel "
        "storm chart signal wharf current"
    ).split()
    # A label-derived nonce guarantees a distinct prompt prefix: the word ring
    # is short, so two labels can otherwise rotate into the same filler.
    para = f"Run {seed_label}. " + " ".join(
        words[(seed + i * 7) % len(words)] for i in range(24)
    ) + ". "
    base_repeat = 110 if args.regime == "short" else 660
    template_kwargs = {"enable_thinking": args.thinking == "on"}

    def ask(messages, max_tokens):
        payload = {
            "model": args.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "chat_template_kwargs": template_kwargs,
        }
        t0 = time.perf_counter()
        resp = api("/v1/chat/completions", payload)
        return resp, time.perf_counter() - t0

    if args.mode == "qa":
        rows = []
        for i, (question, expect) in enumerate(QA):
            resp, wall = ask([{"role": "user", "content": question}], 1600)
            msg = resp["choices"][0]["message"]
            answer = (msg.get("content") or "").strip()
            passed = expect.lower() in answer.lower()
            rows.append(
                {
                    "q": i + 1,
                    "expected": expect,
                    "answer": answer[:160],
                    "pass": passed,
                    "wall_s": round(wall, 2),
                }
            )
            print(f"[{args.label}] Q{i + 1}: {'pass' if passed else 'FAIL'}", flush=True)
        sampler.stop_flag.set()
        sampler.join(timeout=3)
        (out_dir / "qa.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(f"[{args.label}] QA {sum(r['pass'] for r in rows)}/{len(rows)}", flush=True)
        return

    msgs = [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": para * base_repeat + "\n\n" + QUESTIONS[0]},
    ]
    rows = []
    for turn in range(args.turns):
        resp, wall = ask(msgs, args.max_tokens)
        usage = resp["usage"]
        msg_obj = resp["choices"][0]["message"]
        row = {
            "turn": turn + 1,
            "prompt_tokens": usage.get("prompt_tokens"),
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
            "completion_tokens": usage.get("completion_tokens"),
            "client_tps": usage.get("generation_tokens_per_second"),
            "client_ttft": usage.get("time_to_first_token"),
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
    fins = list(FIN_RE.finditer(raw))
    acts = [(m.group(1), int(m.group(2))) for m in ACT_RE.finditer(raw)]
    totals = [m.groups() for m in TOT_RE.finditer(raw)]

    for i, row in enumerate(rows):
        if i < len(fins):
            f = fins[i]
            decode_ms = float(f.group(7)) + float(f.group(8)) + float(f.group(9)) + float(f.group(10))
            row.update(
                {
                    "decode_s": round(decode_ms / 1000, 2),
                    "decode_tok_s": round(int(f.group(2)) / max(decode_ms / 1000, 1e-9), 1),
                    "accept_pct": float(f.group(6)),
                    "cycles": int(f.group(3)),
                }
            )
        if i < len(totals):
            row["server_total_s"] = float(totals[i][1])
            if "decode_s" in row:
                row["ttft_s"] = round(float(totals[i][1]) - row["decode_s"], 2)
        if i < len(acts):
            row["prefilled"] = acts[i][1]
            if "ttft_s" in row:
                row["prefill_tok_s"] = round(row["prefilled"] / max(row["ttft_s"], 1e-9), 1)

    results = {
        "label": args.label,
        "model": args.model,
        "engine": args.engine,
        "mtp": args.mtp,
        "thinking": args.thinking,
        "regime": args.regime,
        "max_tokens": args.max_tokens,
        "rss_peak_gib": round(max(sampler.samples), 2) if sampler.samples else None,
        "rss_final_gib": round(sampler.samples[-1], 2) if sampler.samples else None,
        "rows": rows,
    }
    (out_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    (out_dir / "server-excerpt.log").write_text(raw)
    print(f"[{args.label}] wrote {out_dir}", flush=True)


if __name__ == "__main__":
    main()
