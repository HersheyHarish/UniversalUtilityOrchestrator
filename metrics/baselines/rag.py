"""RAG baseline: embed src/data into chunks, retrieve top-k, answer.

Pipeline:
  1. Build text chunks from src/data:
       - account profile per customer
       - per-invoice itemized billing
       - outage events
       - payment history snapshot
       - policy markdown files
       - daily meter summaries (kwh + spike flag) for July 2019
  2. Embed all chunks locally with sentence-transformers/all-MiniLM-L6-v2
     (same model the project uses in src/agents/billing/rag.py). One-time;
     cached to disk.
  3. Per query: embed query, cosine top-k, send chunks + query to gpt-4o.

Returns the same dict shape as one_shot.run().

Env vars: same as one_shot.py — AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY,
AZURE_OPENAI_DEPLOYMENT, AZURE_OPENAI_API_VERSION.

Cache: metrics/results/rag_embeddings.pkl — delete to force a rebuild.
"""

from __future__ import annotations

import csv
import json
import os
import pickle
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from openai import AzureOpenAI
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]   # repo root
DATA_DIR = ROOT / "src" / "data"
CACHE_PATH = ROOT / "metrics" / "results" / "rag_embeddings.pkl"

TOP_K = 8
EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_SYSTEM = """You are a customer support assistant for a utility company.
Use ONLY the retrieved context below to answer the customer's question.
If the context does not contain relevant information for part of the question,
say so explicitly rather than guessing.

Be concise but complete. Quote specific numbers, dates, and policy references
from the context where they appear.
"""


# =============================================================================
# Chunk builders
# =============================================================================

def _chunks_accounts(billing: dict) -> list[str]:
    out = []
    for cid, acc in billing["accounts"].items():
        plan = acc["plan"]
        addr = acc["service_address"]
        out.append(
            f"[account profile {cid}] {acc['name']} at {addr['city']}, {addr['state']} {addr['zip']}. "
            f"Plan: {plan['name']} (base ${plan['base_charge']}/mo, baseline {plan['baseline_kwh']} kWh, "
            f"overage rate ${plan['overage_rate']}/kWh). "
            f"Loyalty months: {acc.get('loyalty_months')}. Autopay: {acc.get('autopay')}. "
            f"meter_dataid={acc.get('meter_dataid')}."
        )
    return out


def _chunks_invoices(billing: dict) -> list[str]:
    out = []
    for cid, invoices in billing["invoices"].items():
        for inv in invoices:
            items = "; ".join(
                f"{li['description']}: ${li['amount']}"
                + (f" ({li['detail']})" if li.get("detail") else "")
                + (f" [policy {li['policy_ref']}]" if li.get("policy_ref") else "")
                for li in inv.get("line_items", [])
            )
            out.append(
                f"[invoice {inv['invoice_id']}] Customer {cid} for billing window "
                f"{inv['billing_start']} to {inv['billing_end']}. "
                f"Total ${inv['total']}. "
                f"Usage: total_kwh={inv.get('total_kwh')}, peak_kwh={inv.get('peak_kwh')}, "
                f"solar_export={inv.get('solar_export_kwh')}, solar_production={inv.get('solar_production_kwh')}. "
                f"Line items: {items}. Due {inv['due_date']}."
            )
    return out


def _chunks_outages(outages: dict) -> list[str]:
    out = []
    for area, events in outages["outages"].items():
        for ev in events:
            out.append(
                f"[outage {ev['outage_id']}] Area {area}: {ev['event_start']} to {ev['event_end']} "
                f"({ev['duration_minutes']} min). Cause: {ev['cause']}. Scope: {ev['scope']}. "
                f"~{ev['estimated_customers_affected']} customers affected."
            )
    return out


def _chunks_payments(payments: dict) -> list[str]:
    out = []
    for cid, acc in payments["accounts"].items():
        history = "; ".join(
            f"{p['invoice_id']}: due {p['due_date']}, paid {p.get('paid_date','none')} "
            f"(${p['amount_paid']}/{p['amount_due']}, {p['status']})"
            for p in acc.get("payment_history", [])[-12:]
        )
        out.append(
            f"[payment snapshot {cid}] Balance ${acc['current_balance_usd']}. "
            f"Days past due: {acc['days_past_due']}. Stage: {acc['delinquency_stage']}. "
            f"Autopay: {acc.get('autopay_enabled')}. "
            f"Recent history: {history}"
        )
    return out


def _chunks_policies() -> list[str]:
    out = []
    for p in sorted((DATA_DIR / "policies").glob("*.md")):
        text = p.read_text()
        out.append(f"[policy {p.name}]\n{text}")
    return out


def _chunks_meter_daily(billing: dict) -> list[str]:
    """Daily kWh aggregates per customer for July 2019 (the demo window)."""
    dataid_to_cust = {
        str(acc["meter_dataid"]): cid for cid, acc in billing["accounts"].items()
    }
    daily: dict[tuple[str, str], dict] = defaultdict(lambda: {"grid": 0.0, "solar": 0.0, "n": 0})
    csv_path = DATA_DIR / "15minute_data_sample.csv"
    if not csv_path.exists():
        return []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row.get("local_15min", "")
            if not ts.startswith("2019-07"):
                continue
            cid = dataid_to_cust.get(row["dataid"])
            if not cid:
                continue
            day = ts[:10]
            try:
                grid = float(row.get("grid") or 0)
                solar = float(row.get("solar") or 0)
            except ValueError:
                continue
            d = daily[(cid, day)]
            d["grid"] += grid * 0.25     # 15-min sample → kWh
            d["solar"] += solar * 0.25
            d["n"] += 1

    out = []
    for (cid, day), v in sorted(daily.items()):
        out.append(
            f"[meter daily {cid} {day}] "
            f"net grid use {v['grid']:.2f} kWh, solar generation {v['solar']:.2f} kWh "
            f"(over {v['n']} 15-min intervals)."
        )
    return out


def build_corpus() -> list[str]:
    billing = json.loads((DATA_DIR / "demo_billing_data.json").read_text())
    outages = json.loads((DATA_DIR / "demo_outages.json").read_text())
    payments = json.loads((DATA_DIR / "demo_payments.json").read_text())
    chunks = (
        _chunks_accounts(billing)
        + _chunks_invoices(billing)
        + _chunks_outages(outages)
        + _chunks_payments(payments)
        + _chunks_policies()
        + _chunks_meter_daily(billing)
    )
    return chunks


# =============================================================================
# Embedding (cached)
# =============================================================================

def _client() -> AzureOpenAI:
    endpoint_raw = os.environ["AZURE_OPENAI_ENDPOINT"]
    endpoint = endpoint_raw.split("/openai")[0].split("/api/")[0].rstrip("/")
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    )


_EMBED_MODEL: SentenceTransformer | None = None


def _embed_model() -> SentenceTransformer:
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        _EMBED_MODEL = SentenceTransformer(EMBED_MODEL_NAME)
    return _EMBED_MODEL


def _embed_texts(texts: list[str]) -> np.ndarray:
    """Local CPU embedding; returns L2-normalized (n, d) float32."""
    vecs = _embed_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def load_or_build_index() -> tuple[list[str], np.ndarray]:
    if CACHE_PATH.exists():
        with CACHE_PATH.open("rb") as f:
            obj = pickle.load(f)
        return obj["chunks"], obj["embeddings"]

    print("[rag] Building corpus...")
    chunks = build_corpus()
    print(f"[rag] {len(chunks)} chunks built; embedding with {EMBED_MODEL_NAME}...")
    embeddings = _embed_texts(chunks)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("wb") as f:
        pickle.dump({"chunks": chunks, "embeddings": embeddings}, f)
    print(f"[rag] cached embeddings → {CACHE_PATH}")
    return chunks, embeddings


# =============================================================================
# Retrieval + answer
# =============================================================================

_INDEX_CACHE: tuple[list[str], np.ndarray] | None = None


def _get_index() -> tuple[list[str], np.ndarray]:
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        _INDEX_CACHE = load_or_build_index()
    return _INDEX_CACHE


def _topk(query_vec: np.ndarray, embeddings: np.ndarray, k: int) -> list[int]:
    sims = embeddings @ query_vec
    return np.argsort(-sims)[:k].tolist()


def run(query: str, customer_id: str | None = None) -> dict:
    """Single retrieval + LLM call. Matches one_shot.run() return shape."""
    chunks, embeddings = _get_index()
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    client = _client()

    started = time.perf_counter()

    # Embed the (possibly customer-anchored) query locally
    embed_input = query if not customer_id else f"customer_id={customer_id}: {query}"
    qvec = _embed_texts([embed_input])[0]

    idxs = _topk(qvec, embeddings, TOP_K)
    context = "\n\n".join(f"--- doc {i+1} ---\n{chunks[idx]}" for i, idx in enumerate(idxs))

    user_msg = (
        (f"[customer_id={customer_id}]\n" if customer_id else "")
        + f"Question: {query}\n\nRetrieved context:\n{context}"
    )

    resp = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        max_completion_tokens=1500,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    text = resp.choices[0].message.content or ""
    usage = resp.usage
    total_tokens = usage.total_tokens if usage else 0  # local embeddings cost nothing
    return {
        "response": text,
        "agents_used": [],
        "total_latency_ms": latency_ms,
        "planner_tokens": 0,
        "synth_tokens": total_tokens,
        "total_tokens": total_tokens,
        "retrieved_chunk_ids": idxs,
    }


if __name__ == "__main__":
    out = run("Why was CUST-1001 charged so much for July 2019?", "CUST-1001")
    print(json.dumps({k: v for k, v in out.items() if k != "response"}, indent=2))
    print("\n--- response ---\n" + out["response"])
