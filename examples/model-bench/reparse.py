#!/usr/bin/env python3
"""Rebuild a benchmark run's results.json from the server trace log.

Recovers metrics for runs whose client-side collection crashed, without
re-running GPU work. Extracts per-turn: prompt/out tokens, server total,
MTP primed/decode/accept, snapshot sizes. Client-only fields (reasoning
chars, RSS) are null.

Usage: reparse.py --label NAME --start HH:MM:SS --end HH:MM:SS [--tz-offset H]
Server log timestamps are local time; pass --start/--end in that same clock.
"""
import argparse
import json
import re
from pathlib import Path

STATE = Path.home() / "models/qwen38-omlx/state"
LOG = STATE / "logs/server.log"

FIN_RE = re.compile(
    r"(\d\d:\d\d:[\d,.]+) .*MTP\[(\d+)\] finish=(\w+) tokens=(\d+) cycles=(\d+) "
    r"tok/cycle=[\d.]+ accept=(\d+)/(\d+) \(([\d.]+)%\).*"
    r"timing\[backbone=([\d.]+)ms mtp=([\d.]+)ms sample=([\d.]+)ms cache=([\d.]+)ms\]"
)
ACT_RE = re.compile(
    r"(\d\d:\d\d:[\d,.]+) .*MTP path activated for uid=(\d+) .*primed=(\d+)"
)
TOT_RE = re.compile(
    r"(\d\d:\d\d:[\d,.]+) - omlx\.server - INFO - \[-\] - Chat completion: "
    r"model=\S+, (\d+) tokens in ([\d.]+)s \(([\d.]+) tok/s\), prompt: (\d+), "
    "finish_reason=(\\w+)"
)
SNAP_RE = re.compile(r"storing (\d+)/(\d+) tokens")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} (\d\d):(\d\d):([\d,.]+)")


def ts_sec(stamp):
    h, m, s = stamp.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    args = ap.parse_args()

    raw = LOG.read_text(errors="replace")
    t0, t1 = ts_sec(args.start), ts_sec(args.end)

    def line_sec(line):
        m = TS_RE.match(line)
        if not m:
            return -1
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(
            m.group(3).replace(",", ".")
        )

    lines = [ln for ln in raw.splitlines() if 0 <= line_sec(ln) and t0 <= line_sec(ln) <= t1]
    events = []
    for ln in lines:
        fm = FIN_RE.search(ln)
        if fm:
            events.append(("fin", ts_sec(fm.group(1)), fm))
            continue
        am = ACT_RE.search(ln)
        if am:
            events.append(("act", ts_sec(am.group(1)), am))
            continue
        tm = TOT_RE.search(ln)
        if tm:
            events.append(("tot", ts_sec(tm.group(1)), tm))

    events = [e for e in events if t0 <= e[1] <= t1]
    events.sort(key=lambda e: e[1])

    acts = [(e[2].group(2), int(e[2].group(3))) for e in events if e[0] == "act"]
    fins = {e[2].group(2): e[2] for e in events if e[0] == "fin"}
    tots = [e[2] for e in events if e[0] == "tot"]

    rows = []
    window_text = "\n".join(lines)
    snap_iter = [
        (int(a), int(b)) for a, b in SNAP_RE.findall(window_text)
    ]

    for i, tm in enumerate(tots):
        out_tok = int(tm.group(2))
        total_s = float(tm.group(3))
        prompt = int(tm.group(5))
        row = {
            "turn": i + 1,
            "prompt_tokens": prompt,
            "cached_tokens": None,
            "completion_tokens": out_tok,
            "reasoning_chars": None,
            "content_chars": None,
            "client_wall_s": None,
            "server_total_s": total_s,
            "finish_reason": tm.group(6),
            "server_tok_s": float(tm.group(4)),
        }
        if i < len(acts):
            uid, primed = acts[i]
            row["prefilled"] = primed
            f = fins.get(uid)
            if f:
                decode_ms = (
                    float(f.group(9)) + float(f.group(10))
                    + float(f.group(11)) + float(f.group(12))
                )
                row.update(
                    {
                        "decode_s": round(decode_ms / 1000, 2),
                        "decode_tok_s": round(int(f.group(4)) / max(decode_ms / 1000, 1e-9), 1),
                        "accept_pct": float(f.group(8)),
                        "cycles": int(f.group(5)),
                        "finish_mtp": f.group(3),
                    }
                )
                row["ttft_s"] = round(total_s - decode_ms / 1000, 2)
                row["prefill_tok_s"] = round(
                    primed / max(row["ttft_s"], 1e-9), 1
                )
        rows.append(row)

    results = {
        "label": args.label,
        "source": "reparse-from-log",
        "rows": rows,
        "snapshots_stored": snap_iter,
        "rss_gib": None,
    }
    out_dir = STATE / "benchmarks" / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=1))
    (out_dir / "server-excerpt.log").write_text(window_text)

    print(f"label={args.label} turns={len(rows)}")
    for r in rows:
        print(
            f"T{r['turn']}: prompt={r['prompt_tokens']} prefilled={r.get('prefilled')} "
            f"out={r['completion_tokens']} total={r['server_total_s']}s "
            f"decode={r.get('decode_tok_s')} tok/s accept={r.get('accept_pct')}% "
            f"ttft={r.get('ttft_s')}s prefill_rate={r.get('prefill_tok_s')}"
        )
    rates = [r["decode_tok_s"] for r in rows if r.get("decode_tok_s")]
    if rates:
        print(f"avg decode = {sum(rates)/len(rates):.1f} tok/s")


if __name__ == "__main__":
    main()
