"""Resolve a PaymentRiskRequest to an enriched payload of inputs."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.agents.shared.query_parsing import (
    extract_customer_id,
    normalize_customer_id,
)

from .payment_risk_models import PaymentRiskRequest


def resolve_inputs(
    request: PaymentRiskRequest,
    billing: dict[str, Any],
    payments: dict[str, Any],
) -> dict[str, Any]:
    query = (request.query or "Assess payment risk").strip()

    customer_id = request.customer_id or extract_customer_id(query)
    if not customer_id:
        raise ValueError(
            "Payment-risk queries must include a customer id, for example `customer CUST-1001`."
        )
    customer_id = normalize_customer_id(customer_id)

    if customer_id not in billing.get("accounts", {}):
        raise ValueError(f"Unknown customer_id (no billing record): {customer_id}")
    if customer_id not in payments.get("accounts", {}):
        raise ValueError(f"No payment record on file for {customer_id}.")

    snapshot_date = payments.get("as_of_date")
    if request.as_of:
        raw_as_of = request.as_of
    elif snapshot_date:
        raw_as_of = str(snapshot_date)
    else:
        raw_as_of = date.today().isoformat()

    try:
        as_of = date.fromisoformat(raw_as_of[:10])
    except ValueError:
        as_of = date.today()

    all_invoices = billing.get("invoices", {}).get(customer_id, [])
    invoices = [inv for inv in all_invoices if inv.get("billing_end", "") <= as_of.isoformat()]

    return {
        "customer_id": customer_id,
        "billing_account": billing["accounts"][customer_id],
        "payments_account": payments["accounts"][customer_id],
        "invoices": invoices,
        "as_of": as_of,
        "params": request,
    }
