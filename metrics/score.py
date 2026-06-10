"""score.py — read JSONL run logs and produce a summary CSV + console report.

Reads:
    metrics/results/orchestrator_runs.jsonl
    metrics/results/one_shot_runs.jsonl

Writes:
    metrics/results/summary.csv               (per-row: task × system × run, all metrics)
    metrics/results/aggregate_by_system.csv   (one row per system: means)
    metrics/results/aggregate_by_category.csv (rows: category × system)

Metrics computed:
  - agent_precision / agent_recall / agent_f1  (vs. expected_agents)
  - fact_coverage   = fraction of expected_facts found in the answer (substring,
                      case-insensitive). Numeric-tolerance handled for $ amounts.
  - total_latency_ms
  - reasoning_overhead_ms  (orchestrator only: planner + mapping + synth wall-clock)
  - tokens_total
  - paraphrase_consistency (computed at aggregate step per group)

Note on "task_success": this script does NOT auto-judge success — that's a
human task. fact_coverage is a useful proxy; the human pass adds a binary
success/fail column to summary.csv afterwards.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _lcs_ratio(expected: list[str], actual: list[str]) -> float:
    """Longest-common-subsequence length / len(expected). Order-sensitive.

    For single-agent expected lists this collapses to "was the agent used?".
    For multi-hop, rewards keeping the relative order even if extra agents are
    inserted in between.
    """
    if not expected:
        return 1.0 if not actual else 0.0
    m, n = len(expected), len(actual)
    if n == 0:
        return 0.0
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if expected[i - 1] == actual[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[m][n] / m


def _actual_sequence_from_trace(trace: dict | None, fallback_agents: list[str]) -> list[str]:
    """Pull the actual agent invocation order from the trace's steps array.

    Falls back to the (unordered) agents_used list when no trace is available.
    """
    if not trace:
        return list(fallback_agents)
    steps = trace.get("steps") or []
    ordered = []
    for s in sorted(steps, key=lambda x: x.get("started_at") or ""):
        name = s.get("agent_name")
        if name and s.get("status") in (None, "completed"):
            ordered.append(name)
    return ordered or list(fallback_agents)


def _weighted_agent_f1(
    required: list[str], optional: list[str], actual: list[str],
    required_weight: float = 1.0, optional_weight: float = 0.3,
) -> tuple[float, float, float]:
    """Weighted F1: required agents are essential, optional ones are bonus.

    A system that calls all required agents + extras scores high on recall but
    can still be penalized on precision (over-calling). A system that calls
    only required agents scores high on both.
    """
    req_set = set(required)
    opt_set = set(optional)
    act_set = set(actual)

    # Weighted true positives by category
    req_tp = sum(required_weight for a in req_set if a in act_set)
    opt_tp = sum(optional_weight for a in opt_set if a in act_set)

    total_expected_weight = required_weight * len(req_set) + optional_weight * len(opt_set)
    weighted_recall = (req_tp + opt_tp) / total_expected_weight if total_expected_weight else 1.0

    # Precision: of the agents actually called, how many were expected (req or opt)?
    if not act_set:
        weighted_precision = 1.0 if not (req_set | opt_set) else 0.0
    else:
        # Required hits weighted higher, optional hits at full credit, extras at 0.
        hit_weight = sum(required_weight for a in act_set if a in req_set) + \
                     sum(optional_weight for a in act_set if a in opt_set)
        # Precision normalizes against actual call weight (treat extras as weight 0.3, like optional)
        actual_weight = sum(required_weight if a in req_set else
                            optional_weight if a in opt_set else
                            optional_weight for a in act_set)
        weighted_precision = hit_weight / actual_weight if actual_weight else 0.0

    if (weighted_precision + weighted_recall) == 0:
        f1 = 0.0
    else:
        f1 = 2 * weighted_precision * weighted_recall / (weighted_precision + weighted_recall)
    return weighted_precision, weighted_recall, f1


def _agent_f1(expected: list[str], actual: list[str]) -> tuple[float, float, float]:
    exp = set(expected)
    act = set(actual)
    if not exp and not act:
        return 1.0, 1.0, 1.0
    if not act:
        return 0.0, 0.0, 0.0
    tp = len(exp & act)
    precision = tp / len(act) if act else 0.0
    recall = tp / len(exp) if exp else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def _fact_coverage(facts: list[str], answer: str) -> float:
    if not facts:
        return 1.0
    text = answer.lower()
    hits = 0
    for fact in facts:
        f = fact.lower().strip()
        if f == "$":
            # any dollar amount counts
            if re.search(r"\$\s?\d", text):
                hits += 1
        elif f in text:
            hits += 1
    return hits / len(facts)


def _extract_trace_latencies(trace: dict | None) -> dict:
    """Pull breakdown latencies from the registry trace if available.

    agent_exec_sum_ms      sum of per-step latencies (parallel steps double-count)
    mapping_latency_ms     sum of schema-mapper latency across steps
    """
    out = {
        "mapping_latency_ms": 0,
        "agent_exec_sum_ms": 0,
    }
    if not trace:
        return out
    steps = trace.get("steps") or []
    out["mapping_latency_ms"] = sum(s.get("mapping_latency_ms") or 0 for s in steps)
    out["agent_exec_sum_ms"] = sum(s.get("latency_ms") or 0 for s in steps)
    return out


def _trace_token_total(trace: dict | None) -> int:
    if not trace:
        return 0
    steps = trace.get("steps") or []
    return sum(s.get("llm_tokens_used") or 0 for s in steps)


_TASKS_BY_ID: dict[str, dict] | None = None


def _current_tasks() -> dict[str, dict]:
    """Load the *current* tasks.json so re-runs of score.py pick up new
    annotations (required_agents, expected_sequence, etc.) without needing
    to re-run eval."""
    global _TASKS_BY_ID
    if _TASKS_BY_ID is None:
        tasks_path = ROOT / "tasks.json"
        _TASKS_BY_ID = {
            t["task_id"]: t
            for t in json.loads(tasks_path.read_text())["tasks"]
        }
    return _TASKS_BY_ID


def _load_task_success() -> dict[tuple, int]:
    """Load (task_id, system, run_idx) -> 0/1 from task_success.csv if it exists."""
    p = RESULTS_DIR / "task_success.csv"
    if not p.exists():
        return {}
    out: dict[tuple, int] = {}
    with p.open() as f:
        for row in csv.DictReader(f):
            out[(row["task_id"], row["system"], int(row["run_idx"]))] = int(row["task_success"])
    return out


def _load_llm_judge() -> dict[tuple, dict]:
    """Load (task_id, system, run_idx) -> {internal_consistency, completeness,
    groundedness, actionability, judge_overall, task_success_llm} from
    llm_judge.csv if it exists."""
    p = RESULTS_DIR / "llm_judge.csv"
    if not p.exists():
        return {}
    out: dict[tuple, dict] = {}
    with p.open() as f:
        for row in csv.DictReader(f):
            key = (row["task_id"], row["system"], int(row["run_idx"]))
            out[key] = {
                "internal_consistency": int(row.get("internal_consistency") or 0),
                "completeness": int(row.get("completeness") or 0),
                "groundedness": int(row.get("groundedness") or 0),
                "actionability": int(row.get("actionability") or 0),
                "judge_overall": float(row.get("judge_overall") or 0),
                "task_success_llm": row.get("task_success_llm", "").lower() in ("true", "1"),
            }
    return out


def _load_fact_check() -> dict[tuple, dict]:
    p = RESULTS_DIR / "fact_check.csv"
    if not p.exists():
        return {}
    out: dict[tuple, dict] = {}
    with p.open() as f:
        for row in csv.DictReader(f):
            key = (row["task_id"], row["system"], int(row["run_idx"]))
            out[key] = {
                "numerical_accuracy": float(row["numerical_accuracy"]) if row["numerical_accuracy"] else None,
                "hallucination_rate": float(row["hallucination_rate"]) if row["hallucination_rate"] else None,
                "n_claims_total": int(row["n_claims_total"]) if row["n_claims_total"] else 0,
                "n_claims_scored": int(row["n_claims_scored"]) if row["n_claims_scored"] else 0,
            }
    return out


_TASK_SUCCESS_CACHE: dict[tuple, int] | None = None
_LLM_JUDGE_CACHE: dict[tuple, dict] | None = None
_FACT_CHECK_CACHE: dict[tuple, dict] | None = None


def score_row(record: dict) -> dict:
    global _TASK_SUCCESS_CACHE, _LLM_JUDGE_CACHE, _FACT_CHECK_CACHE
    if _TASK_SUCCESS_CACHE is None:
        _TASK_SUCCESS_CACHE = _load_task_success()
    if _LLM_JUDGE_CACHE is None:
        _LLM_JUDGE_CACHE = _load_llm_judge()
    if _FACT_CHECK_CACHE is None:
        _FACT_CHECK_CACHE = _load_fact_check()

    # Refresh task data from the current tasks.json so re-scoring picks up
    # any new ground-truth annotations without re-running eval.
    task = dict(record["task"])
    fresh = _current_tasks().get(record["task_id"])
    if fresh:
        task.update(fresh)
    result = record.get("result") or {}
    answer = result.get("response", "")
    actual_agents = result.get("agents_used", [])
    p, r, f = _agent_f1(task.get("expected_agents", []), actual_agents)
    wp, wr, wf = _weighted_agent_f1(
        task.get("required_agents", []),
        task.get("optional_agents", []),
        actual_agents,
    )
    fact_cov = _fact_coverage(task.get("expected_facts", []), answer)
    ts_key = (record["task_id"], record["system"], record["run_idx"])
    task_success = _TASK_SUCCESS_CACHE.get(ts_key, "")
    judge = _LLM_JUDGE_CACHE.get(ts_key, {})
    fact = _FACT_CHECK_CACHE.get(ts_key, {})

    trace = result.get("trace")
    trace_latencies = _extract_trace_latencies(trace)
    tokens = result.get("total_tokens") or _trace_token_total(trace)

    actual_sequence = _actual_sequence_from_trace(trace, actual_agents)
    seq_acc = _lcs_ratio(task.get("expected_sequence", task.get("expected_agents", [])),
                         actual_sequence)

    total_latency = result.get("total_latency_ms", 0)
    agent_exec = trace_latencies["agent_exec_sum_ms"]
    # Reasoning overhead = total wall-clock - sum of agent step latencies.
    # For systems without traces (one_shot, rag), overhead == total (all reasoning).
    reasoning_overhead = total_latency - agent_exec if agent_exec else total_latency
    overhead_ratio = round(reasoning_overhead / total_latency, 3) if total_latency else 0.0

    return {
        "task_id": record["task_id"],
        "system": record["system"],
        "run_idx": record["run_idx"],
        "category": task.get("category", ""),
        "paraphrase_group": task.get("paraphrase_group", ""),
        "expected_agents": "|".join(task.get("expected_agents", [])),
        "actual_agents": "|".join(actual_agents),
        "expected_sequence": "|".join(task.get("expected_sequence", [])),
        "actual_sequence": "|".join(actual_sequence),
        "agent_precision": round(p, 3),
        "agent_recall": round(r, 3),
        "agent_f1": round(f, 3),
        "weighted_precision": round(wp, 3),
        "weighted_recall": round(wr, 3),
        "weighted_f1": round(wf, 3),
        "sequence_accuracy": round(seq_acc, 3),
        "fact_coverage": round(fact_cov, 3),
        "task_success": task_success,
        "judge_overall": judge.get("judge_overall", ""),
        "judge_consistency": judge.get("internal_consistency", ""),
        "judge_completeness": judge.get("completeness", ""),
        "judge_groundedness": judge.get("groundedness", ""),
        "judge_actionability": judge.get("actionability", ""),
        "judge_task_success": judge.get("task_success_llm", ""),
        "numerical_accuracy": fact.get("numerical_accuracy", "") if fact.get("numerical_accuracy") is not None else "",
        "hallucination_rate": fact.get("hallucination_rate", "") if fact.get("hallucination_rate") is not None else "",
        "n_claims_scored": fact.get("n_claims_scored", 0),
        "total_latency_ms": total_latency,
        "agent_exec_sum_ms": agent_exec,
        "reasoning_overhead_ms": reasoning_overhead,
        "overhead_ratio": overhead_ratio,
        "mapping_latency_ms": trace_latencies["mapping_latency_ms"],
        "tokens": tokens,
        "steps_completed": result.get("steps_completed", ""),
        "error": record.get("error", ""),
        "answer_chars": len(answer),
    }


def write_per_row(rows: list[dict], out: Path) -> None:
    if not rows:
        return
    fields = list(rows[0].keys())
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def aggregate_by(rows: list[dict], key_field: str) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r[key_field], r["system"])].append(r)
    out = []
    for (key, system), items in sorted(groups.items()):
        out.append({
            key_field: key,
            "system": system,
            "n": len(items),
            "agent_f1_mean": round(mean(i["agent_f1"] for i in items), 3),
            "fact_coverage_mean": round(mean(i["fact_coverage"] for i in items), 3),
            "latency_ms_mean": int(mean(i["total_latency_ms"] for i in items)),
            "tokens_mean": int(mean(i["tokens"] for i in items)),
        })
    return out


def paraphrase_consistency(rows: list[dict]) -> dict:
    """For each (system, paraphrase_group), fraction of pairs with overlapping agent sets (Jaccard>=0.5)."""
    by_system_group: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if not r["paraphrase_group"]:
            continue
        by_system_group[(r["system"], r["paraphrase_group"])].append(r)

    system_scores: dict[str, list[float]] = defaultdict(list)
    for (system, _), items in by_system_group.items():
        if len(items) < 2:
            continue
        agent_sets = [set(i["actual_agents"].split("|")) - {""} for i in items]
        pair_scores = []
        for i in range(len(agent_sets)):
            for j in range(i + 1, len(agent_sets)):
                a, b = agent_sets[i], agent_sets[j]
                if not a and not b:
                    pair_scores.append(1.0)
                    continue
                jaccard = len(a & b) / len(a | b) if (a | b) else 0.0
                pair_scores.append(1.0 if jaccard >= 0.5 else 0.0)
        if pair_scores:
            system_scores[system].append(mean(pair_scores))

    return {s: round(mean(v), 3) for s, v in system_scores.items()}


def main() -> int:
    files = list(RESULTS_DIR.glob("*_runs.jsonl"))
    if not files:
        print(f"No *_runs.jsonl in {RESULTS_DIR}. Run run_eval.py first.")
        return 1

    records: list[dict] = []
    for p in files:
        records.extend(load_jsonl(p))

    rows = [score_row(r) for r in records]
    write_per_row(rows, RESULTS_DIR / "summary.csv")

    agg_sys = aggregate_by(rows, "category")  # placeholder; replaced below
    # by system
    by_system: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_system[r["system"]].append(r)

    print("\n=== Aggregate by system ===")
    sys_rows = []
    para_scores = paraphrase_consistency(rows)
    for system, items in sorted(by_system.items()):
        ts_vals = [i["task_success"] for i in items if i["task_success"] != ""]
        judge_vals = [float(i["judge_overall"]) for i in items if i["judge_overall"] not in ("", None)]
        judge_succ_vals = [bool(i["judge_task_success"]) for i in items if i["judge_task_success"] != ""]
        action_vals = [int(i["judge_actionability"]) for i in items if i["judge_actionability"] not in ("", None)]
        num_acc_vals = [float(i["numerical_accuracy"]) for i in items if i["numerical_accuracy"] not in ("", None)]
        hal_vals = [float(i["hallucination_rate"]) for i in items if i["hallucination_rate"] not in ("", None)]
        rec = {
            "system": system,
            "n": len(items),
            "task_success_rate": round(mean(ts_vals), 3) if ts_vals else "",
            "judge_success_rate": round(mean(judge_succ_vals), 3) if judge_succ_vals else "",
            "judge_overall_mean": round(mean(judge_vals), 2) if judge_vals else "",
            "judge_actionability_mean": round(mean(action_vals), 2) if action_vals else "",
            "numerical_accuracy_mean": round(mean(num_acc_vals), 3) if num_acc_vals else "",
            "hallucination_rate_mean": round(mean(hal_vals), 3) if hal_vals else "",
            "agent_f1_mean": round(mean(i["agent_f1"] for i in items), 3),
            "weighted_f1_mean": round(mean(i["weighted_f1"] for i in items), 3),
            "sequence_accuracy_mean": round(mean(i["sequence_accuracy"] for i in items), 3),
            "fact_coverage_mean": round(mean(i["fact_coverage"] for i in items), 3),
            "latency_ms_mean": int(mean(i["total_latency_ms"] for i in items)),
            "overhead_ratio_mean": round(mean(i["overhead_ratio"] for i in items), 3),
            "tokens_mean": int(mean(i["tokens"] for i in items)),
            "paraphrase_consistency": para_scores.get(system, 0.0),
        }
        sys_rows.append(rec)
        def _fmt(v, fmt=".2f"):
            return format(v, fmt) if isinstance(v, (int, float)) and v != "" else "n/a"

        print(f"  {system:<14} n={rec['n']:<4} "
              f"JdgSucc={_fmt(rec['judge_success_rate'])} "
              f"JdgOvr={_fmt(rec['judge_overall_mean'])} "
              f"JdgAct={_fmt(rec['judge_actionability_mean'])} "
              f"NumAcc={_fmt(rec['numerical_accuracy_mean'])} "
              f"HalRt={_fmt(rec['hallucination_rate_mean'])} "
              f"wF1={_fmt(rec['weighted_f1_mean'])} "
              f"Seq={_fmt(rec['sequence_accuracy_mean'])} "
              f"Lat={rec['latency_ms_mean']}ms")

    write_per_row(sys_rows, RESULTS_DIR / "aggregate_by_system.csv")

    print("\n=== Aggregate by category ===")
    cat_rows = aggregate_by(rows, "category")
    for r in cat_rows:
        print(f"  {r['category']:<14} {r['system']:<14} "
              f"F1={r['agent_f1_mean']:.2f}  FactCov={r['fact_coverage_mean']:.2f}  "
              f"Latency={r['latency_ms_mean']}ms")
    write_per_row(cat_rows, RESULTS_DIR / "aggregate_by_category.csv")

    print(f"\nWrote {RESULTS_DIR}/summary.csv, aggregate_by_system.csv, aggregate_by_category.csv")
    print("Next: add a `task_success` 0/1 column to summary.csv by hand (60 rows ≈ 20 min) and re-aggregate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
