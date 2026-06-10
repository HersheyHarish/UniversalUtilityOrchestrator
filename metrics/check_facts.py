"""Numerical fact checking and hallucination rate.

Why both in one pass: both metrics work by extracting numerical claims from a
response and checking them against some ground truth. The only difference is
what counts as ground truth.

Method:
  1. Extract numerical claims from each response with regex:
       - $amounts ($35.75, $250.66, $1,234)
       - kWh / kW figures
       - durations in minutes/hours/days
       - percentages
       - temperatures (°F)
       - dates (July 21 2019, etc. — too noisy to fact-check reliably; skipped)

  2. Build per-(customer, month) ground truth from src/data:
       - All invoice line item amounts and totals
       - All outage durations
       - Meter totals from the 15-min CSV aggregated to month
       - Customer plan rates and baselines

  3. For each numerical claim in a response:
       - "matched"      = appears in ground truth within tolerance
       - "hallucinated" = no matching value within tolerance
       - "unscored"     = unit unrecognized or no ground truth for that customer

  4. Metrics per response:
       - numerical_accuracy = matched / (matched + hallucinated)
       - hallucination_rate = hallucinated / (matched + hallucinated)
       - n_claims_total
       - n_claims_scored

Outputs metrics/results/fact_check.csv with per-row metrics, ready to merge into summary.csv.

Important caveat documented in the writeup: the deployed agents return values
different from src/data (e.g. their billing API returns $250.66; src/data has
$35.75). To be fair, we cross-check against BOTH src/data values AND any agent
outputs found in the trace. A claim that matches either is "matched."
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
DATA_DIR = ROOT.parent / "src" / "data"

# Tolerance for numerical matching: a claim is "matched" if it's within
# this fraction of any ground-truth value. 1% accounts for rounding.
REL_TOLERANCE = 0.01
ABS_TOLERANCE_DOLLARS = 0.50   # within $0.50 always counts as a match
ABS_TOLERANCE_MINUTES = 2      # within 2 min for durations


# =============================================================================
# Claim extraction
# =============================================================================

_PATTERNS = [
    # Dollar amounts: $35.75, $1,234.56, $25
    ("dollars",   re.compile(r"\$\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)")),
    # kWh: 306.49 kWh, 1391.8 kWh
    ("kwh",       re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*kWh", re.IGNORECASE)),
    # Minutes (outage durations): 510 minutes, 45 min
    ("minutes",   re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:minutes?|mins?)\b", re.IGNORECASE)),
    # Temperature: 98.2°F, 84°F
    ("fahrenheit", re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*°?\s*F\b", re.IGNORECASE)),
    # Percentages: 7.2%, 25%
    ("percent",   re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")),
]


def _normalize(num_str: str) -> float:
    return float(num_str.replace(",", ""))


def extract_claims(text: str) -> list[tuple[str, float]]:
    """Return list of (unit, value) numerical claims found in the response."""
    claims: list[tuple[str, float]] = []
    for unit, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            try:
                claims.append((unit, _normalize(m.group(1))))
            except ValueError:
                continue
    return claims


# =============================================================================
# Ground-truth construction
# =============================================================================

def build_ground_truth() -> dict[str, dict[str, set[float]]]:
    """Per (customer_id, unit) -> set of valid numerical values.

    Keys are like 'CUST-1001|dollars', 'CUST-1001|kwh', 'CUST-1002|minutes'.
    All July 2019 values (the demo window). For unit-less / area-wide values
    (weather, outages), values are stored under the SERVICE_AREA key as well.
    """
    truth: dict[str, set[float]] = defaultdict(set)

    billing = json.loads((DATA_DIR / "demo_billing_data.json").read_text())
    outages = json.loads((DATA_DIR / "demo_outages.json").read_text())

    # Customer profile + plan rates
    for cid, acc in billing["accounts"].items():
        plan = acc["plan"]
        truth[f"{cid}|dollars"].add(float(plan["base_charge"]))
        truth[f"{cid}|kwh"].add(float(plan["baseline_kwh"]))

    # Invoices (every line item + total + total_kwh)
    for cid, invoices in billing["invoices"].items():
        for inv in invoices:
            truth[f"{cid}|dollars"].add(float(inv["total"]))
            truth[f"{cid}|kwh"].add(float(inv.get("total_kwh", 0)))
            truth[f"{cid}|kwh"].add(float(inv.get("peak_kwh", 0)))
            truth[f"{cid}|kwh"].add(float(inv.get("solar_export_kwh", 0) or 0))
            truth[f"{cid}|kwh"].add(float(inv.get("solar_production_kwh", 0) or 0))
            for li in inv.get("line_items", []):
                truth[f"{cid}|dollars"].add(abs(float(li["amount"])))

    # Outages — area-keyed, but our two customers live in known service areas
    cust_to_area = {
        "CUST-1001": "78712",   # Austin
        "CUST-1002": "97201",   # Portland
    }
    for cid, area in cust_to_area.items():
        for ev in outages.get("outages", {}).get(area, []):
            truth[f"{cid}|minutes"].add(float(ev["duration_minutes"]))

    return truth


# =============================================================================
# Trace-output ground truth (for orchestrator/langgraph fairness)
# =============================================================================

def extract_trace_numbers(record: dict) -> set[tuple[str, float]]:
    """Pull every numerical claim from agent outputs the system actually saw.
    This makes each system's own data source count as ground truth, so we
    don't penalize a system for citing what its agents returned even if
    src/data says something different. We extract from:
      - orchestrator: trace.steps[].result
      - langgraph:    result.tool_outputs[] (ToolMessage content)
    """
    out: set[tuple[str, float]] = set()
    result = record.get("result") or {}

    # Orchestrator path
    trace = result.get("trace")
    if trace:
        for step in trace.get("steps") or []:
            result_text = step.get("result") or step.get("output_raw")
            text = (json.dumps(result_text) if isinstance(result_text, (dict, list))
                    else result_text if isinstance(result_text, str) else "")
            for unit, value in extract_claims(text):
                out.add((unit, value))

    # LangGraph path
    for tool_out in result.get("tool_outputs") or []:
        if isinstance(tool_out, str):
            for unit, value in extract_claims(tool_out):
                out.add((unit, value))

    return out


# =============================================================================
# Per-record scoring
# =============================================================================

def _matches(unit: str, value: float, candidates: set[float]) -> bool:
    if value in candidates:
        return True
    abs_tol = ABS_TOLERANCE_DOLLARS if unit == "dollars" else (
              ABS_TOLERANCE_MINUTES if unit == "minutes" else 0.0)
    for c in candidates:
        if abs(c - value) <= abs_tol:
            return True
        if c != 0 and abs(c - value) / abs(c) <= REL_TOLERANCE:
            return True
    return False


def score_record(record: dict, static_truth: dict[str, set[float]]) -> dict:
    task = record["task"]
    customer_id = task.get("customer_id") or ""
    response = (record.get("result") or {}).get("response", "")
    claims = extract_claims(response)

    trace_truth_pairs = extract_trace_numbers(record)  # set of (unit, value)
    trace_truth_by_unit: dict[str, set[float]] = defaultdict(set)
    for u, v in trace_truth_pairs:
        trace_truth_by_unit[u].add(v)

    matched = 0
    hallucinated = 0
    unscored = 0
    for unit, value in claims:
        # Skip claims with no plausible ground truth (e.g. 12-month, 5 days)
        # for units we don't have ground truth for.
        candidates_static = static_truth.get(f"{customer_id}|{unit}", set())
        candidates_trace = trace_truth_by_unit.get(unit, set())
        combined = candidates_static | candidates_trace
        if not combined:
            unscored += 1
            continue
        if _matches(unit, value, combined):
            matched += 1
        else:
            hallucinated += 1

    scored = matched + hallucinated
    return {
        "n_claims_total": len(claims),
        "n_claims_scored": scored,
        "n_matched": matched,
        "n_hallucinated": hallucinated,
        "numerical_accuracy": round(matched / scored, 3) if scored else "",
        "hallucination_rate": round(hallucinated / scored, 3) if scored else "",
    }


def load_records() -> list[dict]:
    out: list[dict] = []
    for p in sorted(RESULTS.glob("*_runs.jsonl")):
        for line in p.read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def main() -> int:
    truth = build_ground_truth()
    print(f"ground truth: {sum(len(v) for v in truth.values())} values across {len(truth)} customer-unit buckets")

    records = load_records()
    print(f"scoring {len(records)} responses ...")

    out_rows: list[dict] = []
    for rec in records:
        scores = score_record(rec, truth)
        out_rows.append({
            "task_id": rec["task_id"],
            "system": rec["system"],
            "run_idx": rec["run_idx"],
            **scores,
        })

    out_path = RESULTS / "fact_check.csv"
    fields = ["task_id", "system", "run_idx",
              "n_claims_total", "n_claims_scored",
              "n_matched", "n_hallucinated",
              "numerical_accuracy", "hallucination_rate"]
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    print(f"wrote {out_path}")

    # Aggregate by system
    by_sys: dict[str, list[dict]] = defaultdict(list)
    for r in out_rows:
        by_sys[r["system"]].append(r)

    print("\n=== Numerical accuracy / hallucination by system ===")
    for sysn in sorted(by_sys):
        items = by_sys[sysn]
        scored_items = [i for i in items if i["n_claims_scored"]]
        if not scored_items:
            print(f"  {sysn:<14} n_scored=0  (no scorable claims)")
            continue
        acc = mean(float(i["numerical_accuracy"]) for i in scored_items)
        hal = mean(float(i["hallucination_rate"]) for i in scored_items)
        total_claims = mean(i["n_claims_total"] for i in items)
        scored_claims = mean(i["n_claims_scored"] for i in items)
        print(f"  {sysn:<14} n={len(items):<3} scored_responses={len(scored_items):<3} "
              f"avg_claims={total_claims:.1f} avg_scored={scored_claims:.1f}  "
              f"NumAcc={acc:.2%}  HalRate={hal:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
