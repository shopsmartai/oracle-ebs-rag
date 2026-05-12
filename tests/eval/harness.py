"""
Eval harness for the Talk-to-EBS RAG pipeline.

For each question in golden.yaml:
  1. Retrieval recall — was `expected_note` in top-k?
  2. Must-contain checks — substring assertions on the answer
  3. Must-not-contain checks — substring assertions (forbidden claims)
  4. LLM-as-judge — Claude Haiku scores answer quality 1-5

Outputs:
  - tests/eval/results.json  (per-question results)
  - prints a summary table to stdout

Usage:
    uv run python tests/eval/harness.py             # full run
    uv run python tests/eval/harness.py --ids Q-001 # subset
    uv run python tests/eval/harness.py --no-judge  # skip Haiku scoring
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

# Make repo root importable so this script works both as
#   uv run python tests/eval/harness.py
# AND
#   uv run python -m tests.eval.harness
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import yaml

from oracle_ebs_rag.rag import ask
from oracle_ebs_rag.retrieve import retrieve, Hit
from tests.eval import judge as judge_mod
GOLDEN_PATH = REPO_ROOT / "tests" / "eval" / "golden.yaml"
RESULTS_PATH = REPO_ROOT / "tests" / "eval" / "results.json"

K = 6   # top-k retrieved chunks per question


def load_golden() -> list[dict]:
    return yaml.safe_load(GOLDEN_PATH.read_text())


def retrieval_recall(hits: list[Hit], expected_note: str | None) -> bool:
    """Did `expected_note` appear in top-k? For None (out-of-scope), pass automatically."""
    if expected_note is None:
        return True
    return any(h.note_id == expected_note for h in hits)


def fact_check(answer: str, must: list[str], must_not: list[str]) -> dict[str, bool | list]:
    a_lower = answer.lower()
    missing = [s for s in must if s.lower() not in a_lower]
    present_forbidden = [s for s in must_not if s.lower() in a_lower]
    return {
        "must_contain_pass": not missing,
        "must_not_contain_pass": not present_forbidden,
        "missing_required": missing,
        "present_forbidden": present_forbidden,
    }


def run_one(item: dict, use_judge: bool) -> dict[str, Any]:
    question = item["question"]
    expected_note = item.get("expected_note")

    hits = retrieve(question, k=K)
    result = ask(question, k=K, stream=False)
    answer = result.answer

    facts = fact_check(answer, item.get("must_contain", []) or [],
                       item.get("must_not_contain", []) or [])

    judge_score = None
    judge_reason = None
    if use_judge:
        j = judge_mod.judge(question, answer, item)
        judge_score = j["score"]
        judge_reason = j["reason"]

    return {
        "id": item["id"],
        "category": item.get("category", ""),
        "question": question,
        "expected_note": expected_note,
        "retrieved_top_notes": [h.note_id for h in hits],
        "retrieval_recall_pass": retrieval_recall(hits, expected_note),
        "must_contain_pass": facts["must_contain_pass"],
        "must_not_contain_pass": facts["must_not_contain_pass"],
        "missing_required": facts["missing_required"],
        "present_forbidden": facts["present_forbidden"],
        "judge_score": judge_score,
        "judge_reason": judge_reason,
        "answer_preview": answer[:240],
        "usage": result.usage,
    }


def summary(results: list[dict]) -> dict[str, float | int]:
    n = len(results)
    recall = sum(1 for r in results if r["retrieval_recall_pass"]) / n
    must_pass = sum(1 for r in results if r["must_contain_pass"]) / n
    must_not_pass = sum(1 for r in results if r["must_not_contain_pass"]) / n
    judge_scores = [r["judge_score"] for r in results if r["judge_score"] is not None]
    judge_avg = statistics.mean(judge_scores) if judge_scores else float("nan")

    return {
        "n": n,
        "retrieval_recall":  round(recall, 3),
        "must_contain":      round(must_pass, 3),
        "must_not_contain":  round(must_not_pass, 3),
        "judge_avg":         round(judge_avg, 3) if judge_scores else None,
    }


def print_summary(s: dict, results: list[dict]) -> None:
    print("\n─── Eval Summary ─────────────────────────────")
    print(f"Questions:           {s['n']}")
    print(f"Retrieval recall@{K}: {s['retrieval_recall']:.1%}")
    print(f"Must-contain pass:   {s['must_contain']:.1%}")
    print(f"Must-not-contain:    {s['must_not_contain']:.1%}")
    if s["judge_avg"] is not None:
        print(f"Judge avg (1-5):     {s['judge_avg']:.2f}")
    print("──────────────────────────────────────────────")

    failed = [r for r in results if not (
        r["retrieval_recall_pass"]
        and r["must_contain_pass"]
        and r["must_not_contain_pass"]
    )]
    if failed:
        print(f"\n{len(failed)} test(s) failed:")
        for r in failed:
            print(f"  [{r['id']}] {r['question'][:60]}")
            if not r["retrieval_recall_pass"]:
                print(f"    retrieval: expected {r['expected_note']}, "
                      f"got top notes {r['retrieved_top_notes']}")
            if r["missing_required"]:
                print(f"    missing:   {r['missing_required']}")
            if r["present_forbidden"]:
                print(f"    forbidden: {r['present_forbidden']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="*", help="Run only these IDs")
    parser.add_argument("--no-judge", action="store_true", help="Skip LLM judging")
    args = parser.parse_args()

    golden = load_golden()
    if args.ids:
        golden = [g for g in golden if g["id"] in args.ids]
    if not golden:
        print("No questions matched.")
        return 1

    print(f"Running eval on {len(golden)} question(s) (judge={'off' if args.no_judge else 'on'})...")
    results = []
    for i, item in enumerate(golden, 1):
        print(f"  [{i}/{len(golden)}] {item['id']}: {item['question'][:60]}")
        try:
            results.append(run_one(item, use_judge=not args.no_judge))
        except Exception as e:
            print(f"    ERROR: {type(e).__name__}: {e}")
            results.append({
                "id": item["id"], "error": f"{type(e).__name__}: {e}",
                "retrieval_recall_pass": False,
                "must_contain_pass": False, "must_not_contain_pass": False,
                "judge_score": None,
            })

    s = summary(results)
    RESULTS_PATH.write_text(json.dumps(
        {"summary": s, "results": results}, indent=2, default=str
    ))
    print_summary(s, results)
    print(f"\nResults written to {RESULTS_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
