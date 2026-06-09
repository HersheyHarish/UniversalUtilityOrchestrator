"""run_eval.py — run every task against every system, write JSONL.

Outputs:
    metrics/results/orchestrator_runs.jsonl
    metrics/results/one_shot_runs.jsonl

Each line is one (task_id, system, run_idx) tuple. After this finishes, run
`score.py` to compute aggregates.

Env vars required:
    FUNC_URL, FUNC_KEY                  (from `source azure/.env.deploy`)
    REGISTRY_URL, REGISTRY_KEY          (same)
    AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT  (for baseline)
    REGISTRY_SESSION_TOKEN              (optional; used to fetch detailed traces)

Usage:
    cd <repo root>
    source azure/.env.deploy
    export AZURE_OPENAI_API_KEY=$(az keyvault secret show --vault-name $KV_NAME --name openai-key --query value -o tsv)
    export AZURE_OPENAI_ENDPOINT=https://llm-ua-aryag01.services.ai.azure.com
    export AZURE_OPENAI_DEPLOYMENT=gpt-4o
    python metrics/run_eval.py --runs 2 --systems orchestrator,one_shot
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
TASKS_PATH = ROOT / "tasks.json"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))
from baselines import langgraph_agent, one_shot, rag  # noqa: E402


def call_orchestrator(query: str, customer_id: str | None) -> dict:
    """POST /api/chat, then GET /api/traces/{session_id} for the detailed trace."""
    func_url = os.environ["FUNC_URL"]
    func_key = os.environ["FUNC_KEY"]
    reg_url = os.environ["REGISTRY_URL"]
    reg_key = os.environ["REGISTRY_KEY"]
    session_token = os.environ.get("REGISTRY_SESSION_TOKEN", "")

    payload = {"message": query}
    if customer_id:
        payload["customer_id"] = customer_id

    started = time.perf_counter()
    with httpx.Client(timeout=180.0) as client:
        chat_resp = client.post(
            f"{func_url}/api/chat",
            params={"code": func_key},
            json=payload,
        )
        chat_resp.raise_for_status()
        chat_data = chat_resp.json()
        wall_ms = int((time.perf_counter() - started) * 1000)

        # Fetch the detailed trace (latency breakdown, per-step status).
        trace = None
        session_id = chat_data.get("session_id")
        if session_id and session_token:
            try:
                trace_resp = client.get(
                    f"{reg_url}/api/traces/{session_id}",
                    params={"code": reg_key},
                    headers={"X-Session-Token": session_token},
                )
                if trace_resp.status_code == 200:
                    trace = trace_resp.json()
            except httpx.HTTPError:
                pass

    return {
        "response": chat_data.get("response", ""),
        "agents_used": chat_data.get("agents_used", []),
        "steps_completed": chat_data.get("steps_completed", 0),
        "session_id": session_id,
        "plan_id": chat_data.get("plan_id"),
        "total_latency_ms": wall_ms,
        "trace": trace,
    }


def run_system(system: str, task: dict) -> dict:
    if system == "orchestrator":
        return call_orchestrator(task["query"], task.get("customer_id"))
    elif system == "one_shot":
        return one_shot.run(task["query"], task.get("customer_id"))
    elif system == "rag":
        return rag.run(task["query"], task.get("customer_id"))
    elif system == "langgraph":
        return langgraph_agent.run(task["query"], task.get("customer_id"))
    raise ValueError(f"unknown system: {system}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2, help="runs per (task, system)")
    ap.add_argument("--systems", default="orchestrator,one_shot,rag",
                    help="comma-separated subset to run")
    ap.add_argument("--task-filter", default="",
                    help="only run tasks whose task_id contains this substring")
    ap.add_argument("--append", action="store_true",
                    help="append to existing JSONL instead of overwriting")
    args = ap.parse_args()

    with TASKS_PATH.open() as f:
        tasks = json.load(f)["tasks"]
    if args.task_filter:
        tasks = [t for t in tasks if args.task_filter in t["task_id"]]

    systems = [s.strip() for s in args.systems.split(",") if s.strip()]

    for system in systems:
        out_path = RESULTS_DIR / f"{system}_runs.jsonl"
        mode = "a" if args.append else "w"
        print(f"\n=== {system}  ->  {out_path}  ({len(tasks)} tasks × {args.runs} runs, mode={mode}) ===")
        with out_path.open(mode) as out:
            for task in tasks:
                for run_idx in range(args.runs):
                    print(f"  [{system}] {task['task_id']} run={run_idx} ...", end=" ", flush=True)
                    try:
                        result = run_system(system, task)
                        record = {
                            "task_id": task["task_id"],
                            "system": system,
                            "run_idx": run_idx,
                            "task": task,
                            "result": result,
                        }
                        out.write(json.dumps(record) + "\n")
                        out.flush()
                        agents = result.get("agents_used", [])
                        print(f"ok ({result['total_latency_ms']}ms, agents={len(agents)})")
                    except Exception as exc:
                        print(f"FAILED: {exc}")
                        out.write(json.dumps({
                            "task_id": task["task_id"],
                            "system": system,
                            "run_idx": run_idx,
                            "task": task,
                            "error": str(exc),
                        }) + "\n")
                        out.flush()

    print("\nDone. Score with: python metrics/score.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
