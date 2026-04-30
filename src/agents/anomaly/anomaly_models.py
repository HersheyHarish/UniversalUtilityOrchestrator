"""Wire-format models for the Anomaly Detection Agent."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AnomalyRequest(BaseModel):
    query: str = "Check spikes"
    user_id: Optional[int] = None
    customer_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_results: int = Field(default=5, ge=1, le=20)


class ResolvedAnomalyRequest(BaseModel):
    query: str
    user_id: int
    customer_id: Optional[str] = None
    start_date: str
    end_date: str
    max_results: int = Field(default=5, ge=1, le=20)
