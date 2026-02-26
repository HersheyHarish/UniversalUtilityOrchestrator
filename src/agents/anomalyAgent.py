from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI(title="Anomaly Detection Agent")


SIMULATED_TARGET = {
    "id": 4550,
    "start_date": "2019-06-24 00:00:00",
    "end_date": "2019-06-29 23:45:00",
}


class OrchestratorStep(BaseModel):
    id: str | None = None
    objective: str | None = None
    required_capabilities: list[str] | None = None
    dependencies: list[str] | None = None
    output_key: str | None = None


class OrchestratorContext(BaseModel):
    dependency_outputs: dict[str, Any] | None = None
    all_step_results: dict[str, Any] | None = None


class OrchestratorPayload(BaseModel):
    query: str
    step: OrchestratorStep | None = None
    context: OrchestratorContext | None = None


DATA_FILE = "../data/processed_energy_data.csv"

def load_data() -> pd.DataFrame:
    data = pd.read_csv(DATA_FILE)
    data["local_15min"] = pd.to_datetime(data["local_15min"], utc=True, errors="coerce")
    print(f"Data loaded from {DATA_FILE}")
    return data

df = load_data()

def _build_spike_response() -> dict[str, Any]:
    start = pd.to_datetime(SIMULATED_TARGET["start_date"], utc=True)
    end = pd.to_datetime(SIMULATED_TARGET["end_date"], utc=True)

    mask = (
        (df["dataid"] == SIMULATED_TARGET["id"])
        & (df["local_15min"] >= start)
        & (df["local_15min"] <= end)
    )
    user_data = df.loc[mask]

    if user_data.empty:
        raise HTTPException(status_code=404, detail="No data found for this ID/Range")

    spikes = user_data[user_data["is_spike_2plus"] == True]  # noqa: E712

    details: list[dict[str, Any]] = []
    for _, row in spikes.iterrows():
        z_value = row.get("z")
        details.append(
            {
                "timestamp": str(row["local_15min"]),
                "usage": round(float(row["y"]), 3),
                "z_score": None if pd.isna(z_value) else round(float(z_value), 2),
            }
        )

    return {
        "user_id": SIMULATED_TARGET["id"],
        "range": f"{SIMULATED_TARGET['start_date']} to {SIMULATED_TARGET['end_date']}",
        "spike_detected": len(details) > 0,
        "count": len(details),
        "details": details,
    }


@app.post("/anomaly_detection_agent")
async def anomaly_detection_agent(payload: OrchestratorPayload) -> dict[str, Any]:
    """
    uses hardcoded user/time window for this version
    """
    try:
        spike_result = _build_spike_response()
        return {
            "agent": "anomaly_detection_agent",
            "status": "completed",
            "step_id": payload.step.id if payload.step else None,
            "objective": payload.step.objective if payload.step else None,
            "hardcoded_target": SIMULATED_TARGET,
            "result": spike_result,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/check-spikes")
async def check_spikes(_: dict[str, Any] | None = None) -> dict[str, Any]:

    try:
        return _build_spike_response()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
