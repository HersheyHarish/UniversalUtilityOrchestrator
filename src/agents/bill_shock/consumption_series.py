"""Per-customer consumption series extraction from raw 15-min meter readings.

ROLE IN THE FLOW
----------------
This file has one job: take the full meter DataFrame (all customers, all time)
and return a single time-indexed Series of kWh values for ONE customer.

The result is a pd.Series where:
  - index = 15-min timestamps (local_15min), e.g. 2019-07-01 00:00, 2019-07-01 00:15, ...
  - values = kWh consumed during that interval (kW × 0.25 h)

This Series is passed into bill_projection_math.py for:
  - build_cycle_profile()  → learns the customer's daily usage shape from past months
  - project_cycle_kwh()    → uses the profile to project end-of-month total

FLOW POSITION: meter DataFrame → consumption_series_kwh → build_response (forecast_response_payloads.py)

CONSUMPTION SOURCE PRIORITY
---------------------------
1. "grid" column (preferred): the net import from the grid in kW.
   - Clipped to 0 so solar export periods (negative values) don't subtract
     from consumption. We care about how much energy the household drew.
   - Example: grid=-0.3 during solar peak → clipped to 0.0 kWh
   - Example: grid=2.4 at 6pm → 2.4 × 0.25 = 0.6 kWh

2. Sum of appliance columns (fallback if no grid column):
   - Any numeric column not in NON_APPLIANCE_COLS is treated as an appliance.
   - Example columns: "dishwasher", "ac", "refrigerator", "dryer"
   - Summed with min_count=1 so rows where all appliances are NaN stay NaN
     (rather than becoming 0), then filled to 0.0 after the × INTERVAL_HOURS step.
"""

from __future__ import annotations

import pandas as pd

from .bill_shock_models import INTERVAL_HOURS, NON_APPLIANCE_COLS


def consumption_series_kwh(df: pd.DataFrame, dataid: int) -> pd.Series:
    """Return a time-indexed kWh Series for a single household.

    Args:
        df:     Full meter DataFrame from cached_meter_data() — all customers.
        dataid: The numeric household id (e.g. 5997 for CUST-1001).

    Returns:
        A pd.Series indexed by local_15min Timestamps, values in kWh.
        Empty Series if dataid has no rows.

    Example output (first 3 rows for dataid=5997):
        local_15min
        2019-07-01 00:00:00    0.125   ← 0.5 kW × 0.25 h
        2019-07-01 00:15:00    0.100
        2019-07-01 00:30:00    0.175
        Name: kwh, dtype: float64
    """
    rows = df[df["dataid"] == int(dataid)].copy()
    if rows.empty:
        return pd.Series(dtype=float)

    # Set timestamp as the index so downstream resampling (resample("D").sum())
    # works without needing an explicit on= column.
    rows = rows.set_index("local_15min").sort_index()

    if "grid" in rows.columns and rows["grid"].notna().any():
        # clip(lower=0): treat solar export periods as 0 grid draw, not negative consumption.
        consumption_kw = rows["grid"].clip(lower=0)
    else:
        # Fallback: sum all appliance-level channels.
        appl_cols = [
            col for col in rows.columns
            if col not in NON_APPLIANCE_COLS and pd.api.types.is_numeric_dtype(rows[col])
        ]
        # min_count=1 preserves NaN when every appliance in a row is NaN.
        consumption_kw = rows[appl_cols].sum(axis=1, min_count=1)

    # Convert kW → kWh by multiplying by the interval length (0.25 hours).
    # fillna(0.0) ensures missing readings contribute 0 rather than propagating NaN.
    return (consumption_kw.fillna(0.0) * INTERVAL_HOURS).rename("kwh")
