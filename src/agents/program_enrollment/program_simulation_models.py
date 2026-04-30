"""Request schema and program catalog for the Program Enrollment Simulation Agent."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


ALL_PROGRAMS = ("level_pay", "installment_plan", "low_income_assistance", "time_of_use")


class ProgramSimRequest(BaseModel):
    query: str = "Simulate enrollment programs"
    customer_id: Optional[str] = None
    programs: Optional[list[str]] = None
    cycle_start: Optional[str] = None
    cycle_end: Optional[str] = None
    projected_bill_usd: Optional[float] = None
    projected_kwh: Optional[float] = None
    installment_count: int = Field(default=3, ge=2, le=12)
    low_income_discount_pct: float = Field(default=0.25, ge=0.0, le=0.75)
    tou_peak_rate: float = Field(default=0.25, gt=0)
    tou_off_peak_rate: float = Field(default=0.08, gt=0)
    assume_eligible: bool = True
    lookback_months: int = Field(default=12, ge=2, le=24)
