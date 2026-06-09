"""LLM-as-judge for cross-system task success evaluation.

Modeled on src/core/evaluator.py's EvaluationService rubric structure,
upgraded for paper-grade comparison:

  - Uses gpt-4o (vs. llama3.1:8b in the existing evaluator) for stronger
    judgment quality.
  - Multi-dimensional rubric (4 axes scored 1-5) instead of single overall score.
  - Cross-system: scores responses from any of orchestrator/one_shot/rag/langgraph
    with identical prompts so the comparison is fair.
  - Runs on already-collected JSONL — no eval re-runs needed.

Rubric (modeled after task-completion criteria, not orchestrator-specific):
  - internal_consistency: specific facts in the response match ground truth (1-5)
  - completeness:     covers all parts of the user's question (1-5)
  - groundedness:     claims are supported by data, not generic (1-5)
  - actionability:    customer knows concrete next steps (1-5)
  - task_success:     binary pass/fail (a customer would feel answered)

Outputs metrics/results/llm_judge.csv keyed by (task_id, system, run_idx).
Merges judge scores into summary.csv automatically.

Cost estimate: ~280 calls × ~2k tokens × $5/1M output = roughly $3 of gpt-4o.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean

from openai import AzureOpenAI

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


_SYSTEM = """You are an evaluation judge for AI customer-support responses at a utility company.

You receive ONE customer question and ONE candidate response. You DO NOT have access to
the customer's actual bill or meter data — DIFFERENT systems being evaluated may have
access to different data sources, so you must NOT penalize a response for citing
specific numbers you cannot verify. Instead, judge response QUALITY independent of
whether the numbers happen to match a canonical source.

Score on FOUR dimensions, 1-5 each:

  internal_consistency: 5 = numbers, dates, and claims cited in the response are
                        consistent with each other (e.g. line items sum to total);
                        1 = response contradicts itself.
  completeness:         5 = addresses every part of the user's question (e.g. for
                        "why is my bill high and was there an outage?" both parts);
                        1 = only addresses one small piece or misses the question.
  groundedness:         5 = response cites SPECIFIC concrete details — dollar amounts,
                        dates, kWh values, outage durations, policy references, etc.;
                        1 = vague generic advice with no specifics ("summer is hotter,
                        usage varies", "contact support for details").
  actionability:        5 = customer leaves with clear concrete next steps;
                        1 = no actionable guidance.

ALSO output:

  task_success: true ONLY IF the response (a) addresses the question, (b) cites
                concrete specifics rather than generic advice, AND (c) does not
                obviously punt with phrases like "I don't have access" or "in general,
                summer bills are higher". A fluent generic answer = task_success=false.
  summary:      one short sentence stating your overall judgment.
  issues:       list of concrete problems with the response (or empty list).

DO NOT penalize specific dollar amounts or numbers as "fabricated" just because you
can't verify them — different systems pull from different backends.

Return ONLY valid JSON, no markdown:
{
  "internal_consistency": 1-5,
  "completeness": 1-5,
  "groundedness": 1-5,
  "actionability": 1-5,
  "task_success": true | false,
  "summary": "...",
  "issues": ["...", "..."]
}"""


def _client() -> AzureOpenAI:
    endpoint_raw = os.environ["AZURE_OPENAI_ENDPOINT"]
    endpoint = endpoint_raw.split("/openai")[0].split("/api/")[0].rstrip("/")
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    )


def _judge_one(client: AzureOpenAI, deployment: str, task: dict, response: str) -> dict:
    """Single judge call. Returns parsed rubric dict or fallback on error."""
    user_msg = (
        f"User question: {task['query']}\n"
        f"Customer ID: {task.get('customer_id','')}\n\n"
        f"Candidate response:\n{response}\n\n"
        f"Rate it per the system prompt and return JSON only."
    )
    try:
        completion = client.chat.completions.create(
            model=deployment,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            max_completion_tokens=600,
        )
        raw = completion.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as exc:
        return {
            "internal_consistency": 0, "completeness": 0,
            "groundedness": 0, "actionability": 0,
            "task_success": False,
            "summary": f"judge error: {exc}",
            "issues": [str(exc)],
        }

    def _clip(v, lo, hi):
        try:
            return max(lo, min(hi, int(round(float(v)))))
        except (TypeError, ValueError):
            return 0

    return {
        "internal_consistency": _clip(data.get("internal_consistency"), 1, 5),
        "completeness":     _clip(data.get("completeness"), 1, 5),
        "groundedness":     _clip(data.get("groundedness"), 1, 5),
        "actionability":    _clip(data.get("actionability"), 1, 5),
        "task_success":     bool(data.get("task_success", False)),
        "summary":          str(data.get("summary") or "")[:500],
        "issues":           [str(i)[:200] for i in (data.get("issues") or [])][:8],
    }


def load_records() -> list[dict]:
    records: list[dict] = []
    for p in sorted(RESULTS.glob("*_runs.jsonl")):
        for line in p.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="",
                    help="comma-separated systems to (re)judge; default: all")
    args = ap.parse_args()
    only_systems = {s.strip() for s in args.systems.split(",") if s.strip()}

    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    client = _client()

    all_records = load_records()
    records = [r for r in all_records if not only_systems or r["system"] in only_systems]
    if only_systems:
        print(f"re-judging only: {only_systems}")
    print(f"judging {len(records)} responses with {deployment} ...")

    out_path = RESULTS / "llm_judge.csv"
    fields = ["task_id", "system", "run_idx",
              "internal_consistency", "completeness", "groundedness", "actionability",
              "judge_overall", "task_success_llm", "summary", "issues"]

    started_all = time.perf_counter()
    rows: list[dict] = []
    for i, rec in enumerate(records, 1):
        task = rec["task"]
        response = (rec.get("result") or {}).get("response", "")
        if not response:
            rows.append({
                "task_id": rec["task_id"], "system": rec["system"], "run_idx": rec["run_idx"],
                "internal_consistency": 0, "completeness": 0, "groundedness": 0, "actionability": 0,
                "task_success_llm": False, "summary": "no response", "issues": "",
            })
            continue

        scores = _judge_one(client, deployment, task, response)
        overall = mean([scores["internal_consistency"], scores["completeness"],
                        scores["groundedness"], scores["actionability"]])
        rows.append({
            "task_id": rec["task_id"], "system": rec["system"], "run_idx": rec["run_idx"],
            "internal_consistency": scores["internal_consistency"],
            "completeness":     scores["completeness"],
            "groundedness":     scores["groundedness"],
            "actionability":    scores["actionability"],
            "judge_overall":    round(overall, 2),
            "task_success_llm": scores["task_success"],
            "summary":          scores["summary"],
            "issues":           "; ".join(scores["issues"]),
        })

        if i % 25 == 0:
            elapsed = time.perf_counter() - started_all
            print(f"  judged {i}/{len(records)} ({elapsed:.0f}s elapsed)")

    # Merge with any existing scores (so partial re-judges preserve prior data)
    existing: dict[tuple, dict] = {}
    if out_path.exists():
        with out_path.open() as f:
            for row in csv.DictReader(f):
                key = (row["task_id"], row["system"], int(row["run_idx"]))
                existing[key] = row
    for r in rows:
        key = (r["task_id"], r["system"], int(r["run_idx"]))
        existing[key] = {k: r[k] for k in fields}
    merged_rows = sorted(existing.values(), key=lambda x: (x["task_id"], x["system"], int(x["run_idx"])))
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(merged_rows)
    print(f"\nwrote {out_path} ({len(merged_rows)} total rows, {len(rows)} new/updated)")

    # Aggregate by system
    by_sys: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_sys[r["system"]].append(r)

    print("\n=== Judge results by system ===")
    for sysn in sorted(by_sys):
        items = by_sys[sysn]
        if not items:
            continue
        succ_rate = sum(1 for i in items if i["task_success_llm"]) / len(items)
        means = {k: mean(i[k] for i in items) for k in ("internal_consistency","completeness","groundedness","actionability")}
        overall = mean(means.values())
        print(f"  {sysn:<14} n={len(items)}  "
              f"FactAcc={means['internal_consistency']:.2f}  "
              f"Compl={means['completeness']:.2f}  "
              f"Ground={means['groundedness']:.2f}  "
              f"Action={means['actionability']:.2f}  "
              f"Overall={overall:.2f}  "
              f"Success={succ_rate:.2%}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
