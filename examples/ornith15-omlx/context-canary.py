#!/usr/bin/env python3
"""Long-context canary for the ornith15-omlx profile.

Sends filler text with a needle at increasing prompt sizes and reports whether
the model retrieves it, plus prefill and decode rates. Writes a JSON evidence
file next to the script. Sizes are in words; the tokenizer roughly doubles them.
"""
from __future__ import annotations

import json
import random
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8086"
NEEDLE = "O codigo secreto do canario e ORNITH-7781-KAPPA."
SIZES = (5_000, 30_000, 85_000)


def main() -> int:
    key = (ROOT / "state/api-key").read_text().strip()
    random.seed(7)
    words = [f"w{i}" for i in range(300)]

    def filler(n: int) -> str:
        return " ".join(random.choice(words) for _ in range(n))

    results = []
    for target in SIZES:
        body = f"{filler(target - 12)} {NEEDLE} {filler(20)}"
        payload = {
            "model": "ornith15-omlx",
            "messages": [
                {
                    "role": "user",
                    "content": body + "\n\nQual e o codigo secreto do canario? Responda so o codigo.",
                }
            ],
            "max_tokens": 200,
            "temperature": 1.0,
            "top_p": 0.95,
        }
        request = urllib.request.Request(
            URL + "/v1/chat/completions",
            json.dumps(payload).encode(),
            {"Content-Type": "application/json", "Authorization": "Bearer " + key},
        )
        started = time.time()
        try:
            response = json.load(urllib.request.urlopen(request, timeout=3600))
        except urllib.error.HTTPError as exc:
            results.append({"words": target, "error": exc.read().decode()[:200]})
            print(f"words={target}: {results[-1]['error']}")
            continue
        elapsed = time.time() - started
        usage = response.get("usage", {})
        answer = (response["choices"][0]["message"].get("content") or "").strip()
        row = {
            "words": target,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "wall_seconds": round(elapsed, 1),
            "prefill_tokens_per_second": round((usage.get("prompt_tokens") or 0) / elapsed),
            "needle_found": NEEDLE.split()[-1] in answer,
            "answer": answer[:120],
        }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False))

    evidence = ROOT / "context-canary-results.json"
    evidence.write_text(json.dumps({"url": URL, "sizes": results}, indent=2) + "\n")
    print(f"evidence: {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())