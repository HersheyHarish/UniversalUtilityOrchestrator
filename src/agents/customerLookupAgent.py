from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="Customer Lookup Agent")

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_FILE = BASE_DIR / "data" / "demo_billing_data.json"


class CustomerLookupRequest(BaseModel):
    query: str
    customer_id: str | None = None


def load_data() -> dict[str, Any]:
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load demo data: {e}")
        return {}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "customer_lookup_agent"}


@app.post("/api/customer_lookup_agent")
def customer_lookup_agent(request: CustomerLookupRequest) -> dict[str, Any]:
    dataset = load_data()
    accounts = dataset.get("accounts", {})
    invoices = dataset.get("invoices", {})

    customer_id = request.customer_id
    if not customer_id:
        import re
        match = re.search(r"CUST-\d+", request.query, re.IGNORECASE)
        if match:
             customer_id = match.group(0).upper()

    if not customer_id or customer_id not in accounts:
         raise HTTPException(
             status_code=404, 
             detail=f"Customer '{customer_id}' not found. Available: {list(accounts.keys())}"
         )

    account = accounts[customer_id]
    customer_invoices = invoices.get(customer_id, [])

    total_billed = sum(inv.get("total", 0.0) for inv in customer_invoices)
    avg_billed = total_billed / len(customer_invoices) if customer_invoices else 0.0
    max_billed = max((inv.get("total", 0.0) for inv in customer_invoices), default=0.0)

    summary = {
        "customer_profile": account,
        "billing_summary": {
            "total_invoices_on_record": len(customer_invoices),
            "total_amount_billed_all_time": round(total_billed, 2),
            "average_monthly_bill": round(avg_billed, 2),
            "highest_monthly_bill": round(max_billed, 2),
        }
    }

    return {
        "agent": "customer_lookup_agent",
        "status": "completed",
        "customer_id": customer_id,
        "output": summary
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port)
