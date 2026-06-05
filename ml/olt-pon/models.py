"""
ML models for FTTx telemetry.

Three detectors, each operating on the long-form telemetry table
produced by `generate_data.py`:

1. detect_rx_drift     - per-ONU rolling baseline z-score + IsolationForest
                          on (mean rx power, std, slope) features
2. detect_optical_budget - linear regression of expected loss given
                            (distance, l2_splitter, moduleclass); flags
                            ONUs whose observed loss residual is large
3. detect_cable_bend   - PELT-style change-point detection on RxPower,
                          confirmed by upstream/downstream loss asymmetry

Each detector returns a DataFrame with one row per (onu_uid) and at least
the columns:
    onu_uid, score, severity, reason
plus detector-specific diagnostics.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import OneHotEncoder


# ---------------------------------------------------------------------------
# 1. RxPower drift / anomaly detection
# ---------------------------------------------------------------------------
def _per_onu_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute summary features per ONU for an Isolation Forest."""
    feats = (
        df.sort_values("timestamp")
        .groupby("onu_uid")
        .agg(
            rx_mean=("onu_rx_power", "mean"),
            rx_std=("onu_rx_power", "std"),
            rx_min=("onu_rx_power", "min"),
            rx_max=("onu_rx_power", "max"),
            rx_first=("onu_rx_power", "first"),
            rx_last=("onu_rx_power", "last"),
            bip_mean=("onu_in_biperr", "mean"),
            bip_max=("onu_in_biperr", "max"),
            temp_mean=("pon_temp", "mean"),
        )
    )
    feats["rx_drop"] = feats["rx_first"] - feats["rx_last"]
    feats["rx_range"] = feats["rx_max"] - feats["rx_min"]
    return feats.fillna(0.0)


def detect_rx_drift(df: pd.DataFrame, contamination: float = 0.05
                    ) -> pd.DataFrame:
    """Detect ONUs whose RxPower has drifted downward or behaves abnormally.

    Combines two signals:
      * Z-score of (rx_last - rx_first) across the fleet  -> drift magnitude
      * IsolationForest on (mean, std, drop, range, bip_max, ...)
    """
    feats = _per_onu_features(df)
    iso = IsolationForest(
        n_estimators=50, contamination=contamination, random_state=0, n_jobs=-1
    )
    X = feats[["rx_mean", "rx_std", "rx_drop", "rx_range",
               "bip_mean", "bip_max"]].values
    iso.fit(X)
    raw = -iso.score_samples(X)   # higher = more anomalous
    feats["if_score"] = raw

    # drift magnitude z-score
    drop_z = (feats["rx_drop"] - feats["rx_drop"].mean()) / (
        feats["rx_drop"].std() + 1e-9
    )
    feats["drift_z"] = drop_z

    # combined score
    feats["score"] = (
        (feats["if_score"] - feats["if_score"].min())
        / (feats["if_score"].max() - feats["if_score"].min() + 1e-9)
        + (drop_z.clip(lower=0) / (drop_z.max() + 1e-9))
    ) / 2

    def label(row):
        if row["drift_z"] > 2:
            return "RxPower drifted >2σ below baseline"
        if row["if_score"] > np.quantile(raw, 1 - contamination):
            return "Behavior pattern outlier (IsolationForest)"
        return "ok"

    feats["reason"] = feats.apply(label, axis=1)
    feats["severity"] = pd.cut(
        feats["score"], bins=[-1, 0.4, 0.7, 1.1],
        labels=["low", "med", "high"]
    )
    return feats.reset_index()


# ---------------------------------------------------------------------------
# 2. Optical budget validation
# ---------------------------------------------------------------------------
def detect_optical_budget(df: pd.DataFrame,
                          residual_threshold_db: float = 2.5,
                          ranging_outlier_m: float = 800.0
                          ) -> pd.DataFrame:
    """Two complementary checks rolled into one detector:

      A. **Optical-loss budget**  - fit LinearRegression of observed
         downstream loss against ranging + vendor + module class.
         Large residuals flag bad splices, dirty connectors, high
         attenuation that the topology + distance don't explain.

      B. **Ranging consistency** - within each L2 splitter group, all
         children share the OLT->splitter path, so their ranging values
         should cluster tightly (only the drop length varies, typically
         <300 m). ONUs whose ranging deviates by >ranging_outlier_m from
         the sibling median are likely **mis-cabled** (labelled under
         the wrong splitter).
    """
    # take the most recent observation per ONU
    last = (df.sort_values("timestamp")
              .groupby("onu_uid", as_index=False)
              .tail(1)).copy()

    last["observed_down_loss"] = last["pon_txpwr"] - last["onu_rx_power"]
    last["observed_up_loss"] = last["onu_tx_power"] - last["pon_rxpwr"]
    last["range_km"] = last["ranging"] / 1000.0

    # --- A. Regression residual ------------------------------------------
    enc = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    cat = enc.fit_transform(
        last[["moduleclass", "vendor"]].astype(str).values
    )
    X = np.hstack([last[["range_km"]].values, cat])
    y = last["observed_down_loss"].values
    reg = LinearRegression().fit(X, y)
    pred = reg.predict(X)
    resid = y - pred

    # --- B. Ranging consistency within L2 splitter -----------------------
    group_median = last.groupby("l2_splitter")["ranging"].transform("median")
    last["ranging_dev_m"] = last["ranging"] - group_median

    out = last[["onu_uid", "olt_name", "ponport", "l1_splitter",
                "l2_splitter", "ranging", "ranging_dev_m",
                "observed_down_loss", "observed_up_loss"]].copy()
    out["expected_down_loss"] = pred
    out["residual_db"] = resid
    out["abs_residual"] = np.abs(resid)

    # combined score
    norm_resid = out["abs_residual"] / (out["abs_residual"].max() + 1e-9)
    norm_rng = (out["ranging_dev_m"].abs()
                / (out["ranging_dev_m"].abs().max() + 1e-9))
    out["score"] = (norm_resid + norm_rng) / 2

    flagged_loss = out["abs_residual"] > residual_threshold_db
    flagged_rng = out["ranging_dev_m"].abs() > ranging_outlier_m
    out["flag"] = flagged_loss | flagged_rng

    out["severity"] = "low"
    out.loc[flagged_loss | flagged_rng, "severity"] = "med"
    out.loc[
        (out["abs_residual"] > residual_threshold_db * 1.8)
        | (out["ranging_dev_m"].abs() > ranging_outlier_m * 1.8),
        "severity"
    ] = "high"

    def label(row):
        msgs = []
        if abs(row["ranging_dev_m"]) > ranging_outlier_m:
            msgs.append(
                f"Ranging {row['ranging_dev_m']:+.0f} m vs sibling median "
                f"— likely mis-cabled / wrong splitter label"
            )
        if abs(row["residual_db"]) > residual_threshold_db:
            direction = "ABOVE" if row["residual_db"] > 0 else "BELOW"
            msgs.append(
                f"Loss {row['residual_db']:+.1f} dB {direction} expected "
                f"— bad splice / dirty connector / SFP mismatch"
            )
        return " · ".join(msgs) if msgs else "ok"

    out["reason"] = out.apply(label, axis=1)
    return out


# ---------------------------------------------------------------------------
# 3. Cable bending detection
# ---------------------------------------------------------------------------
def _changepoint_score(series: np.ndarray, min_seg: int = 6) -> tuple[int, float]:
    """Lightweight binary change-point: find the split point that
    maximally separates the mean of the two halves. Returns
    (index, magnitude) where magnitude is mean(before) - mean(after).
    """
    if len(series) < 2 * min_seg:
        return -1, 0.0
    n = len(series)
    s = np.cumsum(series)
    best_idx = -1
    best_mag = 0.0
    for k in range(min_seg, n - min_seg):
        left_mean = s[k - 1] / k
        right_mean = (s[-1] - s[k - 1]) / (n - k)
        mag = left_mean - right_mean
        if abs(mag) > abs(best_mag):
            best_mag = mag
            best_idx = k
    return best_idx, best_mag


def detect_cable_bend(df: pd.DataFrame,
                      step_threshold_db: float = 1.8,
                      asym_min: float = 0.25
                      ) -> pd.DataFrame:
    """Flag ONUs whose RxPower shows a sudden step-down that is
    asymmetric between downstream and upstream loss (the wavelength-
    dependent signature of macro-bending).
    """
    rows = []
    for uid, sub in df.sort_values("timestamp").groupby("onu_uid"):
        rx = sub["onu_rx_power"].to_numpy()
        down_loss = (sub["pon_txpwr"] - sub["onu_rx_power"]).to_numpy()
        up_loss = (sub["onu_tx_power"] - sub["pon_rxpwr"]).to_numpy()

        idx, mag = _changepoint_score(rx)
        if idx < 0:
            continue

        # downstream extra loss after change-point
        down_step = down_loss[idx:].mean() - down_loss[:idx].mean()
        up_step = up_loss[idx:].mean() - up_loss[:idx].mean()
        asym = down_step - up_step   # positive => downstream lost more

        rows.append(dict(
            onu_uid=uid,
            change_idx=idx,
            change_timestamp=sub["timestamp"].iloc[idx],
            # mag = mean(before) - mean(after) on the rx series itself,
            # which is in dBm; rx dropping means before > after, so mag > 0
            rx_step_db=mag,          # positive = rx dropped
            down_step_db=down_step,
            up_step_db=up_step,
            asymmetry_db=asym,
        ))

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # severity: needs a meaningful step AND positive asymmetry
    is_bend = (out["rx_step_db"] >= step_threshold_db) & (out["asymmetry_db"] >= asym_min)
    out["is_bend"] = is_bend
    out["score"] = (out["rx_step_db"].clip(lower=0)
                    / (out["rx_step_db"].max() + 1e-9)) * \
                   (out["asymmetry_db"].clip(lower=0)
                    / (out["asymmetry_db"].max() + 1e-9))

    def label(row):
        if not row["is_bend"]:
            return "ok"
        return (f"Step drop of {row['rx_step_db']:.1f} dB at "
                f"{row['change_timestamp']:%Y-%m-%d %H:%M}, "
                f"down/up asymmetry {row['asymmetry_db']:.1f} dB "
                f"— bend signature")

    out["reason"] = out.apply(label, axis=1)
    out["severity"] = pd.cut(
        out["rx_step_db"],
        bins=[-1e9, step_threshold_db, step_threshold_db * 2, 1e9],
        labels=["low", "med", "high"]
    )
    return out


# ---------------------------------------------------------------------------
# Composite health score
# ---------------------------------------------------------------------------
def composite_health(drift: pd.DataFrame,
                     budget: pd.DataFrame,
                     bend: pd.DataFrame) -> pd.DataFrame:
    """Merge all three detectors into one health table per ONU."""
    a = drift[["onu_uid", "score"]].rename(columns={"score": "drift_score"})
    b = budget[["onu_uid", "score"]].rename(columns={"score": "budget_score"})
    c = bend[["onu_uid", "score"]].rename(columns={"score": "bend_score"}) \
        if not bend.empty else pd.DataFrame(columns=["onu_uid", "bend_score"])

    out = a.merge(b, on="onu_uid", how="outer") \
           .merge(c, on="onu_uid", how="outer") \
           .fillna(0.0)
    out["composite"] = (out["drift_score"] + out["budget_score"]
                        + out["bend_score"]) / 3
    out["health"] = (100 * (1 - out["composite"])).clip(lower=0, upper=100)
    return out.sort_values("composite", ascending=False).reset_index(drop=True)


def run_all(telemetry_csv: str = "data/telemetry.parquet") -> dict:
    df = pd.read_parquet(telemetry_csv)
    drift = detect_rx_drift(df)
    budget = detect_optical_budget(df)
    bend = detect_cable_bend(df)
    health = composite_health(drift, budget, bend)
    return dict(telemetry=df, drift=drift, budget=budget,
                bend=bend, health=health)


if __name__ == "__main__":
    out = run_all()
    print("--- top RxPower drift candidates ---")
    print(out["drift"].sort_values("score", ascending=False).head(8)
          [["onu_uid", "drift_z", "score", "reason"]].to_string(index=False))
    print("\n--- top budget-deviation candidates ---")
    print(out["budget"].sort_values("abs_residual", ascending=False).head(8)
          [["onu_uid", "ranging", "expected_down_loss", "observed_down_loss",
            "residual_db", "reason"]].to_string(index=False))
    print("\n--- top bend candidates ---")
    print(out["bend"].sort_values("score", ascending=False).head(8)
          [["onu_uid", "rx_step_db", "asymmetry_db", "reason"]].to_string(index=False))
