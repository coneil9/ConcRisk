"""Offline eval harness for the ConcRisk chatbot.

Reads evals/questions.jsonl, runs each question through the agent
against whatever's in DATABASE_URL, and reports per-check-type accuracy.
Exits non-zero when overall accuracy < 90% (SPEC §13).

Before running, seed some fund data:
    uv run python -m concrisk.etl.pipeline \\
        --fund 0001067983 --fund 0001336528 --quarters 2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from concrisk.chat import run_chat

QUESTIONS_FILE = Path(__file__).parent / "questions.jsonl"
PASS_THRESHOLD = 0.90


def _norm(text: str) -> str:
    return text.lower()


def check_contains_all(text: str, expected: dict[str, Any]) -> bool:
    t = _norm(text)
    return all(s.lower() in t for s in expected["contains_all"])


def check_contains_any(text: str, expected: dict[str, Any]) -> bool:
    t = _norm(text)
    return any(s.lower() in t for s in expected["contains_any"])


def check_refusal(text: str, expected: dict[str, Any]) -> bool:
    t = _norm(text)
    return any(s.lower() in t for s in expected["refusal_signal"])


_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def check_numeric(text: str, expected: dict[str, Any]) -> bool:
    """Extract every numeric literal from the response and pass if any is
    within `tolerance` of `value`."""
    target = float(expected["value"])
    tolerance = float(expected.get("tolerance", 0.0))
    for match in _NUMBER_RE.findall(text):
        try:
            n = float(match)
        except ValueError:
            continue
        if abs(n - target) <= tolerance:
            return True
    return False


CHECKS = {
    "contains_all": check_contains_all,
    "contains_any": check_contains_any,
    "refusal": check_refusal,
    "numeric": check_numeric,
}


def load_questions(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def run_one(q: dict[str, Any]) -> tuple[bool, str]:
    """Run one question through the agent, return (passed, response_text)."""
    result = run_chat(q["question"])
    check_fn = CHECKS.get(q["check"])
    if check_fn is None:
        return False, f"unknown check type: {q['check']}"
    return check_fn(result.text, q["expected"]), result.text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_evals")
    parser.add_argument("--limit", type=int, default=None, help="only run the first N questions")
    parser.add_argument("--ids", type=str, default=None, help="comma-separated question IDs to run")
    parser.add_argument("--verbose", "-v", action="store_true", help="print full responses")
    args = parser.parse_args(argv)

    questions = load_questions(QUESTIONS_FILE)
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        questions = [q for q in questions if q["id"] in wanted]
    if args.limit:
        questions = questions[: args.limit]

    print(f"Running {len(questions)} eval questions...\n")

    results: list[dict[str, Any]] = []
    for q in questions:
        try:
            passed, text = run_one(q)
        except Exception as e:
            print(f"  ✗ {q['id']} ERROR: {e}")
            results.append({"id": q["id"], "check": q["check"], "passed": False, "error": str(e)})
            continue
        marker = "✓" if passed else "✗"
        print(f"  {marker} {q['id']}: {q['question'][:70]}")
        if not passed or args.verbose:
            print(f"    expected: {q['expected']}")
            print(f"    got: {text[:250]}{'...' if len(text) > 250 else ''}")
        results.append({"id": q["id"], "check": q["check"], "passed": passed})

    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    overall_pct = 100 * passed_count / total if total else 0
    print(f"\n{passed_count}/{total} passed ({overall_pct:.1f}%)")

    by_check: dict[str, dict[str, int]] = {}
    for r in results:
        entry = by_check.setdefault(r["check"], {"passed": 0, "total": 0})
        entry["total"] += 1
        if r["passed"]:
            entry["passed"] += 1
    print("\nBy check type:")
    for check_name, counts in sorted(by_check.items()):
        pct = 100 * counts["passed"] / counts["total"] if counts["total"] else 0
        print(f"  {check_name:15s} {counts['passed']:2d}/{counts['total']:2d}  ({pct:5.1f}%)")

    if total == 0:
        return 1
    return 0 if passed_count / total >= PASS_THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
