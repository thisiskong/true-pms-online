"""
Run all three ML detectors offline and save results to parquet.

Usage:
    uv run python run_models.py [data_dir]

Reads:   <data_dir>/telemetry.parquet
Writes:  <data_dir>/results_drift.parquet
         <data_dir>/results_budget.parquet
         <data_dir>/results_bend.parquet
         <data_dir>/results_health.parquet
"""

from __future__ import annotations

import os
import sys
import time

import pandas as pd

from models import (
    detect_rx_drift,
    detect_optical_budget,
    detect_cable_bend,
    composite_health,
)


def run(data_dir: str = "data") -> None:
    telem_path = os.path.join(data_dir, "telemetry.parquet")
    if not os.path.exists(telem_path):
        print(f"ERROR: {telem_path} not found. Run load_data.py first.")
        sys.exit(1)

    print(f"Reading {telem_path} ...")
    df = pd.read_parquet(telem_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    print(f"  {len(df):,} rows | {df['onu_uid'].nunique():,} ONUs")

    def step(name, fn, *args):
        print(f"Running {name} ...")
        t0 = time.time()
        result = fn(*args)
        print(f"  done in {time.time() - t0:.1f}s  ({len(result):,} rows)")
        return result

    drift  = step("detect_rx_drift",       detect_rx_drift,        df)
    budget = step("detect_optical_budget", detect_optical_budget,  df)
    bend   = step("detect_cable_bend",     detect_cable_bend,      df)
    health = step("composite_health",      composite_health, drift, budget, bend)

    for name, result in [
        ("results_drift",   drift),
        ("results_budget",  budget),
        ("results_bend",    bend),
        ("results_health",  health),
    ]:
        path = os.path.join(data_dir, f"{name}.parquet")
        result.to_parquet(path, index=False)
        print(f"Wrote {path}")

    print("Done.")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "data")
