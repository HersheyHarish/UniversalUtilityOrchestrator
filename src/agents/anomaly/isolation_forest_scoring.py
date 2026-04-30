"""IsolationForest + z-score scoring for the anomaly detector.

Trains a per-user IsolationForest on the first TRAIN_FRACTION of each user's
history, scores all rows, and combines with a z-score spike flag to produce
the final `is_anomaly` column.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from .consumption_feature_engineering import MIN_OBS_PER_USER

IF_CONTAMINATION = 0.02
ZSCORE_THRESHOLD = 3.0
TRAIN_FRACTION = 0.80

FEATURE_COLS = [
    "total_consumption",
    "grid_export",
    "hour",
    "is_weekend",
    "delta_from_prev",
    "ratio_to_rolling_mean",
    "hourly_zscore",
]

def score_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    df["if_anomaly"] = 0
    df["if_score"] = np.nan
    df["has_model"] = False
    df["split"] = "excluded"

    for user_id in df["dataid"].unique():
        user_rows = df[df["dataid"] == user_id]
        if len(user_rows) < MIN_OBS_PER_USER:
            continue

        split_point = int(len(user_rows) * TRAIN_FRACTION)
        train_rows = user_rows.iloc[:split_point]
        holdout_rows = user_rows.iloc[split_point:]
        df.loc[train_rows.index, "split"] = "train"
        df.loc[holdout_rows.index, "split"] = "holdout"

        train_data = train_rows[FEATURE_COLS].dropna()
        if len(train_data) < MIN_OBS_PER_USER:
            continue

        model = IsolationForest(
            n_estimators=200,
            contamination=IF_CONTAMINATION,
            random_state=42,
            n_jobs=-1,
        )
        scaler = StandardScaler()
        x_train = scaler.fit_transform(train_data)
        model.fit(x_train)

        usable_rows = user_rows[FEATURE_COLS].dropna()
        if usable_rows.empty:
            continue

        x_all = scaler.transform(usable_rows)
        df.loc[usable_rows.index, "if_score"] = model.decision_function(x_all)
        df.loc[usable_rows.index, "if_anomaly"] = (model.predict(x_all) == -1).astype(int)
        df.loc[user_rows.index, "has_model"] = True

    df["zscore_spike"] = (df["hourly_zscore"].abs() > ZSCORE_THRESHOLD).astype(int)
    df["anomaly_signals"] = df["if_anomaly"] + df["zscore_spike"]
    df["is_anomaly"] = (df["anomaly_signals"] >= 1).astype(int)
    return df