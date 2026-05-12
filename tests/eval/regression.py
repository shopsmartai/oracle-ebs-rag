"""
Regression gate — runs in CI on every PR.

Compares the current eval results (tests/eval/results.json) against
the locked-in baseline (tests/eval/baseline.json). Fails the build if
any metric drops more than the allowed tolerance.

When you intentionally improve the pipeline (better chunker, prompt,
model upgrade, etc.), update the baseline by running:
    cp tests/eval/results.json tests/eval/baseline.json
    git add tests/eval/baseline.json
    git commit -m "Update eval baseline: <reason>"

Usage:
    uv run python tests/eval/regression.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_PATH  = REPO_ROOT / "tests" / "eval" / "results.json"
BASELINE_PATH = REPO_ROOT / "tests" / "eval" / "baseline.json"

# Allowed regression (pp = percentage points; 0.05 = 5pp)
TOLERANCE_BY_METRIC = {
    "retrieval_recall": 0.05,
    "must_contain":     0.05,
    "must_not_contain": 0.0,    # zero tolerance — forbidden content is critical
    "judge_avg":        0.3,    # 0.3 points on the 1-5 scale
}


def main() -> int:
    if not RESULTS_PATH.exists():
        print(f"ERROR: {RESULTS_PATH} missing. Run harness.py first.")
        return 2
    if not BASELINE_PATH.exists():
        print(f"NOTE: no baseline yet — first run will create one.")
        print(f"  cp {RESULTS_PATH} {BASELINE_PATH}")
        return 0

    current  = json.loads(RESULTS_PATH.read_text())["summary"]
    baseline = json.loads(BASELINE_PATH.read_text())["summary"]

    failed = False
    print(f"{'Metric':<22} {'Baseline':<12} {'Current':<12} {'Δ':<10} Status")
    print("─" * 70)
    for metric, tol in TOLERANCE_BY_METRIC.items():
        b = baseline.get(metric)
        c = current.get(metric)
        if b is None or c is None:
            print(f"{metric:<22} {'<missing>':<12} {'<missing>':<12} {'-':<10} SKIP")
            continue
        delta = c - b
        # Lower is bad for all metrics here (higher = better)
        is_fail = delta < -tol
        status = "FAIL" if is_fail else "ok"
        if is_fail:
            failed = True
        sign = "+" if delta >= 0 else ""
        print(f"{metric:<22} {b:<12.3f} {c:<12.3f} {sign}{delta:<9.3f} {status}")
    print("─" * 70)
    if failed:
        print("\nREGRESSION DETECTED. Either fix the regression or, if it's "
              "intentional, update tests/eval/baseline.json.")
        return 1
    print("\nNo regressions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
