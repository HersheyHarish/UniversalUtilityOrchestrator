import sys

import numpy as np
import pandas as pd


def calculate_mad(x: pd.Series) -> float:
    """Calculates the Median Absolute Deviation."""
    x = x.dropna()
    if len(x) == 0:
        return np.nan
    median = np.median(x)
    return float(np.median(np.abs(x - median)))


def process_energy_data(input_file: str, output_file: str) -> None:
    """Load, process, and save spike detection features."""
    print(f"Loading {input_file}...")
    df = pd.read_csv(input_file)

    # 1. Clean and Parse
    df["local_15min"] = pd.to_datetime(df["local_15min"], errors="coerce")
    df["y"] = pd.to_numeric(df["grid"], errors="coerce").clip(lower=0)

    # 2. Feature Engineering
    df["dow"] = df["local_15min"].dt.dayofweek
    df["slot"] = df["local_15min"].dt.hour * 4 + (df["local_15min"].dt.minute // 15)

    # 3. Create Baseline
    print("Calculating baselines (this may take a moment)...")
    baseline = (
        df.groupby(["dataid", "dow", "slot"])["y"]
        .agg(med="median", mad=calculate_mad, n="count")
        .reset_index()
    )

    df = df.merge(baseline, on=["dataid", "dow", "slot"], how="left")

    # 4. Statistical Scoring
    eps = 1e-6
    df["sigma_adj"] = (1.4826 * df["mad"]).fillna(0).clip(lower=eps)
    df["z"] = (df["y"] - df["med"]) / df["sigma_adj"]

    # 5. Spike Flagging
    df["is_spike"] = (df["z"] >= 3) & (df["y"] > df["med"])
    df.loc[df["n"] < 8, ["z", "is_spike"]] = [np.nan, False]

    # 6. Persistence Filter (2+ consecutive)
    print("Applying persistence filter...")
    df = df.sort_values(["dataid", "local_15min"])
    df["is_spike_2plus"] = (
        df.groupby("dataid")["is_spike"]
        .transform(lambda s: s & (s.shift(1).fillna(False) | s.shift(-1).fillna(False)))
    )

    # 7. Save Output
    df.to_csv(output_file, index=False)
    print(f"Success! Processed data saved to {output_file}")


if __name__ == "__main__":
    # Hardcoded file names for current testing
    input_path = "../data/15minute_data_newyork.csv"
    output_path = "../data/processed_energy_data.csv"

    try:
        process_energy_data(input_path, output_path)
    except FileNotFoundError:
        print(f"Error: Could not find {input_path}")
        sys.exit(1)
