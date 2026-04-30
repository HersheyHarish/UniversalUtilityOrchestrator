"""Resolve a ProgramSimRequest to an enriched payload of inputs."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.agents.shared.query_parsing import (
    extract_customer_id,
    normalize_customer_id,
    parse_query_dates,
    to_naive,
)

from .program_data_sources import find_invoice_for_cycle
from .program_simulation_models import ALL_PROGRAMS, ProgramSimRequest


def resolve_inputs(
    request: ProgramSimRequest,
    billing: dict[str, Any],
) -> dict[str, Any]:
    query = (request.query or "Simulate enrollment programs").strip()

    customer_id = request.customer_id or extract_customer_id(query)
    if customer_id is None:
        raise ValueError(
            "Program-simulation queries must include a customer id, for example `customer CUST-1001`."
        )
    customer_id = normalize_customer_id(customer_id)

    accounts = billing.get("accounts", {})
    if customer_id not in accounts:
        raise ValueError(f"Unknown customer_id: {customer_id}")

    parsed_start, parsed_end = parse_query_dates(query)
    cycle_start = to_naive(request.cycle_start) if request.cycle_start else parsed_start
    cycle_end = to_naive(request.cycle_end) if request.cycle_end else parsed_end

    requested_programs = request.programs or list(ALL_PROGRAMS)
    invalid = [p for p in requested_programs if p not in ALL_PROGRAMS]
    if invalid:
        raise ValueError(f"Unknown program(s): {invalid}. Supported: {list(ALL_PROGRAMS)}")

    all_invoices = billing.get("invoices", {}).get(customer_id, [])
    invoice = find_invoice_for_cycle(all_invoices, cycle_start, cycle_end)

    # If no cycle window was supplied or parsed from the query, pull it from the
    # resolved invoice so TOU simulation has the meter window it needs.
    if cycle_start is None and invoice is not None and invoice.get("billing_start"):
        cycle_start = pd.Timestamp(invoice["billing_start"])
    if cycle_end is None and invoice is not None and invoice.get("billing_end"):
        cycle_end = pd.Timestamp(invoice["billing_end"])

    # Only use invoices that closed before cycle_start for historical lookback.
    cutoff = cycle_start.strftime("%Y-%m-%d") if cycle_start else "9999-12-31"
    invoices = [inv for inv in all_invoices if inv.get("billing_end", "") < cutoff]

    if request.projected_bill_usd is not None:
        current_bill = float(request.projected_bill_usd)
        bill_source = "from_request"
    elif invoice is not None and "total" in invoice:
        current_bill = float(invoice["total"])
        bill_source = "from_invoice"
    else:
        raise ValueError(
            "No bill amount available. Pass `projected_bill_usd` or pick a cycle that has an invoice on file."
        )

    if request.projected_kwh is not None:
        current_kwh = float(request.projected_kwh)
    elif invoice is not None and "total_kwh" in invoice:
        current_kwh = float(invoice["total_kwh"])
    else:
        current_kwh = 0.0

    return {
        "query": query,
        "customer_id": customer_id,
        "account": accounts[customer_id],
        "invoices": invoices,
        "invoice": invoice,
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "current_bill_usd": current_bill,
        "current_kwh": current_kwh,
        "bill_source": bill_source,
        "programs": requested_programs,
        "params": request,
    }
