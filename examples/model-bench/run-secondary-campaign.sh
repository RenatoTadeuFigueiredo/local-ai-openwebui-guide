#!/usr/bin/env bash
# Secondary-model campaign driver: arms x regimes, then QA, then determinism.
set -u
cd "$(dirname "$0")"

run() {
  echo "=== $*"
  python3 secondary_suite.py "$@" || echo "FAILED: $*"
}

# Throughput arms (thinking off: measures the decode path, not deliberation).
run --label sage-vlm-mtp3-short --regime short --max-tokens 1024
run --label sage-llm-mtp3-short --regime short --engine llm --max-tokens 1024
run --label sage-vlm-mtp0-short --regime short --mtp off --max-tokens 1024
run --label sage-vlm-mtp3-long  --regime long  --max-tokens 1024
run --label sage-llm-mtp3-long  --regime long  --engine llm --max-tokens 1024
run --label sage-vlm-mtp0-long  --regime long  --mtp off --max-tokens 1024

# Quality guard: same 8 questions per arm.
run --label sage-vlm-mtp3-qa --mode qa
run --label sage-llm-mtp3-qa --mode qa --engine llm
run --label sage-vlm-mtp0-qa --mode qa --mtp off

# Determinism: identical prompt space, 3 identical runs.
for i in 1 2 3; do
  run --label "sage-det-$i" --turns 3 --max-tokens 320 --shared-filler
done

echo "=== campaign done"
