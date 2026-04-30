"""Request schema and tier ordering for the Payment Risk & Hardship Agent."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


TIER_RANK = {"low": 0, "moderate": 1, "high": 2, "critical": 3}


class PaymentRiskRequest(BaseModel):
    query: str = "Assess payment risk"
    customer_id: Optional[str] = None
    as_of: Optional[str] = None
    lookback_invoices: int = Field(default=6, ge=2, le=24)
    projected_bill_usd: Optional[float] = None
    bill_shock_severity: Optional[str] = None
