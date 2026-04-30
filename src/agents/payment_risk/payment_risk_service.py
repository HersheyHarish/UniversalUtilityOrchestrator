"""FastAPI entry point for the Payment Risk & Hardship Agent."""

from __future__ import annotations

import warnings
from typing import Any

from fastapi import FastAPI, HTTPException

from .payment_risk_data_sources import cached_billing_data, cached_payments_data
from .payment_risk_request_resolution import resolve_inputs
from .payment_risk_response_payloads import build_response
from .payment_risk_models import PaymentRiskRequest


warnings.filterwarnings("ignore")


app = FastAPI(title="Payment Risk & Hardship Agent")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "payment_risk_hardship_agent"}


@app.post("/api/payment_risk_hardship_agent")
def payment_risk_hardship_agent(request: PaymentRiskRequest) -> dict[str, Any]:
    try:
        billing = cached_billing_data()
        payments = cached_payments_data()
        resolved = resolve_inputs(request, billing, payments)
        return build_response(resolved)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
