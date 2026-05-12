"""
LLM-as-judge: Claude Haiku scores answer quality 1-5.

We use Haiku (not Sonnet) for judging because:
  - It's ~10x cheaper per call, so eval runs are affordable
  - For "did this answer follow the rubric?" it's plenty smart
  - Different model from the answerer (Sonnet) — independent signal
  - Returns structured JSON we can parse

The judge gets the question, the answer, and the test's `must_contain` /
`must_not_contain` lists. It returns:
  { "score": 1-5, "reason": "..." }
"""
from __future__ import annotations

import json
import re

import anthropic

from oracle_ebs_rag.config import settings


JUDGE_MODEL = "claude-haiku-4-5"   # adjust if model name differs in your tier

RUBRIC = """You are grading an AI assistant's answer to a question about
Oracle E-Business Suite (EBS) administration.

Return ONLY a JSON object: {"score": N, "reason": "short explanation"}

Scoring rubric (1-5):
  5 = Excellent. Answer is accurate, cites sources, includes required facts,
      contains no forbidden claims, and would help a DBA solve the problem.
  4 = Good. Mostly correct, minor omission or imprecision; would help.
  3 = Mediocre. Partially correct but missing key required facts OR vague.
  2 = Poor. Incorrect on key points, missing most required facts, or
      contains a forbidden claim.
  1 = Wrong / harmful. Hallucinated commands, destructive suggestions, or
      completely off-topic.

If `must_contain` is non-empty and a required fact is missing, cap score at 3.
If `must_not_contain` contains anything that appears in the answer, cap at 2.
If the answer correctly says "the provided context doesn't cover this", that
is GOOD on out-of-scope questions — score 5 there."""


def judge(question: str, answer: str, item: dict) -> dict:
    """Score an answer 1-5 with a short reason."""
    s = settings()
    if not s.anthropic_api_key:
        return {"score": 0, "reason": "no anthropic key"}

    client = anthropic.Anthropic(api_key=s.anthropic_api_key)

    prompt = f"""QUESTION:
{question}

ANSWER TO GRADE:
{answer}

REQUIRED FACTS (must appear in answer): {item.get('must_contain', [])}
FORBIDDEN CLAIMS (must NOT appear):     {item.get('must_not_contain', [])}
EXPECTED SOURCE NOTE:                    {item.get('expected_note', 'none — out of scope')}

Score this answer per the rubric. Respond with JSON only."""

    resp = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=200,
        system=RUBRIC,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    return _parse_json(text)


def _parse_json(text: str) -> dict:
    """Tolerant JSON parser — handles ```json fences and stray text."""
    m = re.search(r"\{.*?\}", text, re.DOTALL)
    if not m:
        return {"score": 0, "reason": f"unparseable: {text[:120]}"}
    try:
        obj = json.loads(m.group(0))
        score = int(obj.get("score", 0))
        return {"score": max(0, min(5, score)),
                "reason": str(obj.get("reason", ""))[:300]}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return {"score": 0, "reason": f"parse error: {e}"}
