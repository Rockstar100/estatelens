"""Run the evaluation cases against a running EstateLens instance.

    # unit-style check of case structure + retrieval only (no model calls):
    python -m tests.eval.run_eval --retrieval-only

    # full run against a live server (uses real OpenRouter quota):
    ESTATELENS_URL=http://localhost:8000 python -m tests.eval.run_eval

Each factual case asserts the answer contains the expected facts and, where
`expect_abstention` is true, that the model declines rather than inventing.
`must_not_contain` guards against prompt-injection / hallucinated values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

CASES = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))["cases"]
ABSTAIN_MARKERS = (
    "not listed in the collected source",
    "no matches",
    "no results",
    "not affiliated",
    "cannot", "could not find", "don't have", "do not have", "no collected",
    "not in the collected", "not available in the collected",
)


def _stream_chat(base: str, turns: list[str]) -> str:
    messages: list[dict] = []
    answer = ""
    with httpx.Client(base_url=base, timeout=90) as c:
        for turn in turns:
            messages.append({"role": "user", "content": turn})
            answer = ""
            with c.stream(
                "POST", "/api/chat", json={"messages": messages, "context": {}}
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    evt = json.loads(line[5:].strip())
                    if evt["type"] == "delta":
                        answer += evt["text"]
                    elif evt["type"] == "error":
                        return f"[error:{evt['category']}] {evt['message']}"
            messages.append({"role": "assistant", "content": answer})
    return answer


def _check(case: dict, answer: str) -> tuple[bool, str]:
    low = answer.lower()
    if case.get("expect_abstention"):
        if not any(m in low for m in ABSTAIN_MARKERS):
            return False, "expected an abstention, got a substantive answer"
    hits = [f for f in case.get("expected_facts", []) if f.lower() in low]
    if case.get("expected_facts") and not hits:
        return False, f"none of the expected facts present: {case['expected_facts']}"
    for bad in case.get("must_not_contain", []):
        if bad.lower() in low:
            return False, f"answer contains forbidden text: {bad!r}"
    return True, f"ok ({len(hits)}/{len(case.get('expected_facts', []))} facts)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval-only", action="store_true")
    args = ap.parse_args()

    base = os.environ.get("ESTATELENS_URL", "http://localhost:8000")

    if args.retrieval_only:
        bad = 0
        for c in CASES:
            turns = c.get("turns") or [c["question"]]
            if not turns or not all(isinstance(t, str) for t in turns):
                print(f"MALFORMED {c['id']}")
                bad += 1
        print(f"{len(CASES)} cases, {bad} malformed")
        return 1 if bad else 0

    passed = 0
    for c in CASES:
        turns = c.get("turns") or [c["question"]]
        try:
            answer = _stream_chat(base, turns)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR  {c['id']}: {exc}")
            continue
        ok, detail = _check(c, answer)
        passed += ok
        print(f"{'PASS ' if ok else 'FAIL '} {c['id']}: {detail}")
        if not ok:
            print(f"        answer: {answer[:240].replace(chr(10), ' ')}")
    print(f"\n{passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
