"""FastAPI entry point for the Anomaly Detection Agent."""

from __future__ import annotations

import warnings
from typing import Any

from fastapi import FastAPI, HTTPException

from .cached_detection_pipeline import run_detection, cached_billing_data
from .request_resolution import resolve_anomaly_inputs
from .anomaly_response_payloads import build_response
from .anomaly_models import AnomalyRequest

warnings.filterwarnings("ignore")

app = FastAPI(title="Anomaly Detection Agent")

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "anomaly_detection_agent"}

@app.post("/api/anomaly_detection_agent")
def anomaly_detection_agent(request: AnomalyRequest) -> dict[str, Any]:
    try:
        scored = run_detection()
        billing = cached_billing_data()
        resolved = resolve_anomaly_inputs(request, scored, billing)
        return build_response(resolved, scored)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
