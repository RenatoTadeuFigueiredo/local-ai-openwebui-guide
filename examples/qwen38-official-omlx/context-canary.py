#!/usr/bin/env python3
"""Run an authenticated raw-completion context canary against the local profile."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
MODEL_ID = "qwen38-official-omlx"
URL = "http://127.0.0.1:8084/v1/completions"
NATIVE_CONTEXT = 262_144


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-tokens", type=int, default=40_000)
    parser.add_argument("--max-tokens", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=7_200)
    parser.add_argument(
        "--require-mtp",
        action="store_true",
        help="fail unless this request adds fresh MTP activation and summary logs",
    )
    args = parser.parse_args()

    if args.prompt_tokens <= 0 or args.max_tokens <= 0:
        raise SystemExit("prompt and output token counts must be positive")
    if args.prompt_tokens + args.max_tokens > NATIVE_CONTEXT:
        raise SystemExit("requested prompt + output exceeds the native 262144-token window")

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        ROOT / "model",
        local_files_only=True,
        trust_remote_code=False,
    )
    prompt = " x" * args.prompt_tokens
    encoded = tokenizer.encode(prompt, add_special_tokens=False)
    if len(encoded) != args.prompt_tokens:
        raise SystemExit(
            f"fixture tokenization drifted: requested={args.prompt_tokens}, actual={len(encoded)}"
        )

    server_log = STATE / "logs/server.log"
    if not server_log.is_file():
        raise SystemExit("server log is missing; start the profile before this canary")
    log_identity = (server_log.stat().st_dev, server_log.stat().st_ino)
    log_offset = server_log.stat().st_size

    key = (STATE / "api-key").read_text(encoding="utf-8").strip()
    body = {
        "model": MODEL_ID,
        "prompt": prompt,
        "max_tokens": args.max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        URL,
        json.dumps(body).encode(),
        {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
    )

    started = time.monotonic()
    first_content_at = None
    usage = None
    finish_reason = None
    content = []
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                event = json.loads(line[6:])
                usage = event.get("usage") or usage
                for choice in event.get("choices") or []:
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice["finish_reason"]
                    text = (choice.get("text") or "") + (
                        (choice.get("delta") or {}).get("content") or ""
                    )
                    if text:
                        if first_content_at is None:
                            first_content_at = time.monotonic()
                        content.append(text)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {detail[:1000]}") from exc

    ended = time.monotonic()
    if not usage:
        raise SystemExit("server did not return a final usage object")
    if int(usage.get("prompt_tokens", -1)) != args.prompt_tokens:
        raise SystemExit(
            "server/client prompt-token counts differ: "
            f"client={args.prompt_tokens}, server={usage.get('prompt_tokens')}"
        )
    completion_tokens = int(usage.get("completion_tokens", 0))
    if not 0 < completion_tokens <= args.max_tokens:
        raise SystemExit(
            f"unexpected completion count: {completion_tokens} (limit {args.max_tokens})"
        )
    total_tokens = int(usage.get("total_tokens", -1))
    if total_tokens != args.prompt_tokens + completion_tokens:
        raise SystemExit(
            "server returned an inconsistent total-token count: "
            f"prompt={args.prompt_tokens}, completion={completion_tokens}, total={total_tokens}"
        )
    if finish_reason not in {"length", "stop"}:
        raise SystemExit(f"unexpected finish_reason={finish_reason!r}")

    mtp_evidence = False
    try:
        if (server_log.stat().st_dev, server_log.stat().st_ino) == log_identity:
            with server_log.open("r", encoding="utf-8", errors="replace") as log:
                log.seek(log_offset)
                new_log = log.read()
            activated = new_log.rfind("MTP path activated")
            summary = new_log.rfind("MTP[")
            mtp_evidence = activated >= 0 and summary > activated
    except OSError:
        pass
    if args.require_mtp and not mtp_evidence:
        raise SystemExit("request succeeded, but no fresh Lightning MTP activation/summary was found")

    result = {
        "model": MODEL_ID,
        "requested_prompt_tokens": args.prompt_tokens,
        "server_prompt_tokens": usage.get("prompt_tokens"),
        "requested_max_tokens": args.max_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "finish_reason": finish_reason,
        "ttft_seconds": round(first_content_at - started, 3)
        if first_content_at is not None
        else None,
        "wall_seconds": round(ended - started, 3),
        "prompt_tokens_per_second": usage.get("prompt_tokens_per_second")
        or usage.get("prompt_tps"),
        "generation_tokens_per_second": usage.get("generation_tokens_per_second")
        or usage.get("generation_tps"),
        "response_characters": sum(map(len, content)),
        "fresh_mtp_log_evidence": mtp_evidence,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
