#!/usr/bin/env python3
"""Measure where reasoning_effort / enable_thinking changes the rendered
prompt token sequence, to quantify prefix-cache impact of mixing efforts.

Divergence index = first differing token between two renderings of the SAME
conversation. Blocks before floor(idx/2048) stay reusable in the paged
prefix cache; everything after must be re-prefilled.
"""
from pathlib import Path

from transformers import AutoTokenizer

MODEL_DIR = "/Users/renato/models/qwen38-omlx/models/qwen38-omlx"
BLOCK = 2048

FILLER = (
    "The harbor master recorded wind direction, barometer readings and the "
    "names of every vessel that passed the breakwater. "
) * 40


def first_divergence(a_ids, b_ids):
    n = min(len(a_ids), len(b_ids))
    for i in range(n):
        if a_ids[i] != b_ids[i]:
            return i
    return n  # one is a strict prefix of the other


def main():
    tok = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
    msgs = [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": FILLER + "\n\nSummarize in two sentences."},
        {
            "role": "assistant",
            "content": "<think >\nLet me organize the key facts.\n</think >\n\nThe ledger tracks weather and shipping.",
        },
        {"role": "user", "content": "Add one more detail about the gulls."},
    ]

    variants = {}
    candidates = [
        ("(default)", {}),
        ("effort=xhigh", {"reasoning_effort": "xhigh"}),
        ("effort=medium", {"reasoning_effort": "medium"}),
        ("effort=low", {"reasoning_effort": "low"}),
        ("thinking=on", {"enable_thinking": True}),
        ("thinking=off", {"enable_thinking": False}),
    ]
    for label, kwargs in candidates:
        try:
            text = tok.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=True, **kwargs
            )
            variants[label] = tok.encode(text)
            print(f"{label:14s} -> {len(variants[label]):5d} tokens OK")
        except Exception as exc:  # noqa: BLE001
            print(f"{label:14s} -> template rejected {kwargs}: {type(exc).__name__}: {exc}")

    base_label = "(default)"
    base = variants.get(base_label)
    print("\n-- divergence vs default --")
    for label, ids in variants.items():
        if label == base_label:
            continue
        d = first_divergence(base, ids)
        blocks_kept = d // BLOCK
        print(
            f"{label:14s} div@{d:5d} ({d/max(len(base),1)*100:5.1f}% shared) "
            f"=> {blocks_kept} of {(len(base)-1)//BLOCK} blocks reusable"
        )

    print("\n-- cross-effort (xhigh vs medium) --")
    if "effort=xhigh" in variants and "effort=medium" in variants:
        a, b = variants["effort=xhigh"], variants["effort=medium"]
        d = first_divergence(a, b)
        print(
            f"div@{d} => {d // BLOCK} blocks shared, "
            f"re-prefill >= {min(len(a), len(b)) - ((d // BLOCK) * BLOCK)} tokens"
        )

    print("\n-- same effort, conversation grows (sanity) --")
    long_a = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                     reasoning_effort="xhigh")
    grown = msgs + [{"role": "assistant", "content": "Gulls appear daily at dawn."},
                    {"role": "user", "content": "And the tide schedule?"}]
    long_b = tok.apply_chat_template(grown, tokenize=False, add_generation_prompt=True,
                                     reasoning_effort="xhigh")
    ia, ib = tok.encode(long_a), tok.encode(long_b)
    d = first_divergence(ia, ib)
    print(f"div@{d} of {len(ia)} => {d // BLOCK} blocks reusable (expect ~all)")


if __name__ == "__main__":
    main()
