"""Translate an `AnomalyRequest` into a fully-resolved request the detector can run."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.agents.shared.query_parsing import (
    extract_customer_id,
    normalize_customer_id,
    parse_query_dates,
)

from .anomaly_models import AnomalyRequest, ResolvedAnomalyRequest


def resolve_anomaly_inputs(
    request: AnomalyRequest,
    df: pd.DataFrame,
    billing: dict[str, Any],
) -> ResolvedAnomalyRequest:
    """Parse and validate a raw AnomalyRequest into a fully-resolved request.

    The customer → meter_dataid mapping is read from the billing JSON (accounts
    block) rather than hardcoded here, so adding a new customer only requires
    updating demo_billing_data.json, not Python code.

    Args:
        request: Validated Pydantic request from the HTTP caller.
        df:      Fully scored meter DataFrame from run_detection().
        billing: Parsed billing JSON from cached_billing_data().
                 Must contain an "accounts" key where each account has "meter_dataid".
    """
    user_id = request.user_id
    customer_id = request.customer_id
    start_date = request.start_date
    end_date = request.end_date
    query = request.query or "Check spikes"

    if customer_id is None:
        customer_id = extract_customer_id(query)

    if start_date is None or end_date is None:
        parsed_start, parsed_end = parse_query_dates(query)
        if start_date is None and parsed_start is not None:
            start_date = parsed_start.isoformat()
        if end_date is None and parsed_end is not None:
            end_date = parsed_end.isoformat()

    if user_id is None and customer_id is not None:
        normalized_customer_id = normalize_customer_id(customer_id)
        accounts = billing.get("accounts", {})
        if normalized_customer_id not in accounts:
            raise ValueError(f"Unknown customer_id: {customer_id}")
        user_id = int(accounts[normalized_customer_id]["meter_dataid"])
        customer_id = normalized_customer_id

    if user_id is None:
        raise ValueError(
            "Anomaly queries must include a customer id (e.g. CUST-1001) or an explicit numeric user_id."
        )
    if start_date is None or end_date is None:
        raise ValueError(
            "Anomaly queries must include a date range like `2019-07-01 - 2019-07-31` or a month and year like `July 2019`."
        )

    if int(user_id) not in set(df["dataid"].unique()):
        raise ValueError(f"Unknown user_id: {user_id}")

    return ResolvedAnomalyRequest(
        query=query,
        user_id=int(user_id),
        customer_id=normalize_customer_id(customer_id) if customer_id is not None else None,
        start_date=start_date,
        end_date=end_date,
        max_results=request.max_results,
    )
