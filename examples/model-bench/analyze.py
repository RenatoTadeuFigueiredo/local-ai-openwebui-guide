#!/usr/bin/env python3
"""Cross-run analysis for the production benchmark campaign.

Loads state/benchmarks/*/results.json and prints:
  - per-run performance table (decode, accept, TTFT, prefill rate, RSS)
  - per-turn decode vs context position
  - output similarity vs the chosen reference run (quality sanity)
"""
import argparse
import difflib
import json
import statistics
from pathlib import Path

BENCH = Path.home() / "models/qwen38-omlx/state/benchmarks"


def load(label):
    return json.loads((BENCH / label / "results.json").read_text())


def perf_table(runs):
    hdr = (
        f"{'run':<18} {'dec.avg':>8} {'dec.med':>8} {'accept':>7} "
        f"{'Σttft_s':>8} {'pre.tok/s':>9} {'rss.max':>8} {'Σout':>6}"
    )
    print(hdr)
    for label in runs:
        r = load(label)
        rows = r["rows"]
        dec = [x["decode_tok_s"] for x in rows if x.get("decode_tok_s")]
        acc = [x["accept_pct"] for x in rows if x.get("accept_pct")]
        ttft = [x.get("ttft_s") for x in rows if x.get("ttft_s") is not None]
        pre_w = [
            (x["prefilled"], x["prefill_tok_s"])
            for x in rows
            if x.get("prefilled") and x.get("prefill_tok_s")
        ]
        wavg = (
            sum(p * s for p, s in pre_w) / max(sum(p for p, _ in pre_w), 1)
            if pre_w
            else float("nan")
        )
        if not (0 < wavg < 1e6):
            wavg = float("nan")
        rss = (r.get("rss_gib") or {}).get("max")
        out = sum(x["completion_tokens"] or 0 for x in rows)
        print(
            f"{label:<18} {statistics.mean(dec):>8.1f} "
            f"{statistics.median(dec):>8.1f} {statistics.mean(acc):>6.1f}% "
            f"{sum(ttft):>8.1f} {wavg:>9.1f} "
            f"{(f'{rss:.1f}' if rss else '-'):>8} {out:>6}"
        )


def quality_diff(ref_label, other_label):
    ref, oth = load(ref_label), load(other_label)
    print(f"\n-- content similarity {ref_label} (ref) vs {other_label} --")
    ratios = []
    for a, b in zip(ref["rows"], oth["rows"]):
        ta, tb = a.get("content") or "", b.get("content") or ""
        ratio = difflib.SequenceMatcher(None, ta, tb).ratio() if ta and tb else 0.0
        ratios.append(ratio)
        print(
            f"T{a['turn']}: ratio={ratio:.2f} len_ref={len(ta)} len_other={len(tb)}"
        )
    print(f"avg ratio = {statistics.mean(ratios):.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--reference", default=None)
    args = ap.parse_args()

    perf_table(args.runs)

    if args.reference:
        for label in args.runs:
            if label != args.reference:
                quality_diff(args.reference, label)


if __name__ == "__main__":
    main()
