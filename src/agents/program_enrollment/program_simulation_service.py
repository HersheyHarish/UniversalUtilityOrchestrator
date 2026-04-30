"""FastAPI entry point for the Program Enrollment Simulation Agent."""

from __future__ import annotations

import warnings
from typing import Any

from fastapi import FastAPI, HTTPException

from .program_data_sources import cached_billing_data
from .program_request_resolution import resolve_inputs
from .program_response_payloads import build_response
from .program_simulation_models import ProgramSimRequest


warnings.filterwarnings("ignore")


app = FastAPI(title="Program Enrollment Simulation Agent")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "program_enrollment_simulation_agent"}


@app.post("/api/program_enrollment_simulation_agent")
def program_enrollment_simulation_agent(request: ProgramSimRequest) -> dict[str, Any]:
    try:
        billing = cached_billing_data()
        resolved = resolve_inputs(request, billing)
        return build_response(resolved)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
