"""
Synthetic FTTx telemetry generator.

Builds a hierarchical OLT -> PON port -> L1 splitter -> L2 splitter -> ONU
topology and emits realistic time-series telemetry matching the schema in
README.md. Intentionally injects three classes of anomaly so the ML modules
have something to find:

  * RxPower drift   - slow degradation (dirty connector / aging)
  * Mis-cabling     - ONU labelled under wrong splitter group; ranging
                      inconsistent with siblings
  * Cable bending   - sudden step change in RxPower, larger downstream
                      (longer wavelength) than upstream -> asymmetric loss
"""

from __future__ import annotations

import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

RNG = np.random.default_rng(42)

# ---------------------------------------------------------------------------
# Topology parameters
# ---------------------------------------------------------------------------
NUM_OLTS = 2
PORTS_PER_OLT = 8
L2_PER_PON = 4          # 1x4 L1 splitter
ONUS_PER_L2 = 8         # 1x8 L2 splitter
HOURS = 24 * 7          # one week of hourly samples

VENDORS = ["Huawei", "ZTE", "Nokia", "FiberHome"]
MODELS = {
    "Huawei":    ["MA5800-X17", "MA5800-X7"],
    "ZTE":       ["C600", "C320"],
    "Nokia":     ["FX-16", "FX-8"],
    "FiberHome": ["AN6000-17", "AN6000-7"],
}
SITES = ["HCM-01", "HCM-02", "HN-01", "DN-01"]
MODULE_CLASSES = ["ClassB+", "ClassC+"]

# Optical reference values (GPON-ish, dBm)
OLT_TX_NOMINAL = 3.0          # OLT downstream tx power
ONU_TX_NOMINAL = 2.5          # ONU upstream tx power
SPLITTER_LOSS = {4: 7.5, 8: 10.5, 16: 14.0, 32: 17.5}
FIBER_LOSS_DOWN_PER_KM = 0.35  # ~1490 nm
FIBER_LOSS_UP_PER_KM = 0.40    # ~1310 nm


def _pick(seq):
    return seq[RNG.integers(0, len(seq))]


# ---------------------------------------------------------------------------
# Build static topology
# ---------------------------------------------------------------------------
def build_topology() -> pd.DataFrame:
    rows = []
    for olt_idx in range(NUM_OLTS):
        vendor = _pick(VENDORS)
        model = _pick(MODELS[vendor])
        site = _pick(SITES)
        olt_name = f"OLT-{site}-{olt_idx + 1:02d}"

        for port in range(1, PORTS_PER_OLT + 1):
            pon_port = f"0-1-{olt_idx + 1}-{port}"
            mod_class = _pick(MODULE_CLASSES)
            l1_name = f"L1-{olt_name}-P{port}"

            for l2 in range(L2_PER_PON):
                l2_name = f"L2-{olt_name}-P{port}-{l2 + 1}"
                # baseline distance from OLT to L2 splitter (km)
                base_km = RNG.uniform(0.5, 8.0)

                for onu in range(ONUS_PER_L2):
                    onu_id = f"{olt_name}-P{port}-S{l2 + 1}-O{onu + 1}"
                    # extra drop distance from L2 to home (50-300 m)
                    drop_m = RNG.uniform(50, 300)
                    distance_m = base_km * 1000 + drop_m
                    rows.append(
                        dict(
                            olt_name=olt_name,
                            vendor=vendor,
                            model=model,
                            sitename=site,
                            ponport=pon_port,
                            moduleclass=mod_class,
                            l1_splitter=l1_name,
                            l2_splitter=l2_name,
                            ontid=onu + 1,
                            device_serial=f"SN{RNG.integers(10**7, 10**8)}",
                            circuit_id=f"CKT-{RNG.integers(10**6, 10**7)}",
                            onu_uid=onu_id,
                            distance_m=distance_m,
                        )
                    )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Per-ONU loss budget (deterministic ideal, before noise/anomaly)
# ---------------------------------------------------------------------------
def base_loss_db(distance_m: float) -> tuple[float, float]:
    """Return (downstream_loss_db, upstream_loss_db) ignoring bending."""
    km = distance_m / 1000.0
    fiber_down = km * FIBER_LOSS_DOWN_PER_KM
    fiber_up = km * FIBER_LOSS_UP_PER_KM
    # 1x4 L1 + 1x8 L2 -> ~7.5 + 10.5 = 18 dB plus a couple connectors
    splitters = SPLITTER_LOSS[4] + SPLITTER_LOSS[8] + 1.0
    return fiber_down + splitters, fiber_up + splitters


# ---------------------------------------------------------------------------
# Anomaly injection plan
# ---------------------------------------------------------------------------
def plan_anomalies(topo: pd.DataFrame) -> dict[str, dict]:
    """Pick a handful of ONUs and assign them a fault profile."""
    plan: dict[str, dict] = {}
    onus = topo["onu_uid"].tolist()

    # 10 ONUs with slow downward drift
    drift = RNG.choice(onus, size=10, replace=False)
    for u in drift:
        plan[u] = {"type": "drift", "rate_db_per_hr": RNG.uniform(0.02, 0.05)}

    pool = [u for u in onus if u not in plan]

    # 8 ONUs with bend event at a random hour
    bend = RNG.choice(pool, size=8, replace=False)
    for u in bend:
        plan[u] = {
            "type": "bend",
            "start_hour": int(RNG.integers(24, HOURS - 24)),
            "down_loss_db": RNG.uniform(2.0, 5.0),
            # bend loss is larger at longer (downstream) wavelengths;
            # upstream sees ~40-60% of the downstream loss
            "asym_ratio": RNG.uniform(0.4, 0.65),
        }

    pool = [u for u in pool if u not in plan]

    # 5 ONUs mis-cabled: their reported l2_splitter is wrong, so ranging
    # disagrees badly with their listed siblings.
    miscab = RNG.choice(pool, size=5, replace=False)
    for u in miscab:
        plan[u] = {"type": "miscable", "extra_km": RNG.uniform(2.0, 5.0)}

    return plan


# ---------------------------------------------------------------------------
# Time-series generation
# ---------------------------------------------------------------------------
def generate_timeseries(topo: pd.DataFrame, plan: dict) -> pd.DataFrame:
    start = datetime(2026, 5, 15, 0, 0, 0)
    timestamps = [start + timedelta(hours=h) for h in range(HOURS)]

    # precompute baseline per ONU
    topo = topo.copy()
    losses = topo["distance_m"].apply(base_loss_db)
    topo["base_down_loss"] = [a for a, _ in losses]
    topo["base_up_loss"] = [b for _, b in losses]

    # mis-cabling shifts the *effective* distance (so loss disagrees with
    # the reported sibling group, which the budget model uses for prediction)
    for uid, fault in plan.items():
        if fault["type"] == "miscable":
            mask = topo["onu_uid"] == uid
            extra_m = fault["extra_km"] * 1000
            topo.loc[mask, "distance_m"] += extra_m
            new_loss = topo.loc[mask, "distance_m"].apply(base_loss_db).iloc[0]
            topo.loc[mask, "base_down_loss"] = new_loss[0]
            topo.loc[mask, "base_up_loss"] = new_loss[1]

    records = []
    for ts_idx, ts in enumerate(timestamps):
        # Diurnal traffic curve (peaks evening)
        hour = ts.hour
        traffic_mult = 0.4 + 0.6 * np.exp(-((hour - 21) ** 2) / 30)

        for row in topo.itertuples():
            uid = row.onu_uid
            fault = plan.get(uid, {"type": "ok"})

            # Optical noise
            noise_down = RNG.normal(0, 0.15)
            noise_up = RNG.normal(0, 0.2)

            down_loss = row.base_down_loss + noise_down
            up_loss = row.base_up_loss + noise_up

            # Drift fault: ONU rx power slowly drops. Aging connectors /
            # dust attenuate roughly equally at both wavelengths, so the
            # loss is symmetric (this is what distinguishes drift from
            # macro-bending in the detector).
            if fault["type"] == "drift":
                drift_amount = fault["rate_db_per_hr"] * ts_idx
                down_loss += drift_amount
                up_loss += drift_amount

            # Bend fault: step change after start_hour, asymmetric
            if fault["type"] == "bend" and ts_idx >= fault["start_hour"]:
                down_loss += fault["down_loss_db"]
                up_loss += fault["down_loss_db"] * fault["asym_ratio"]

            pon_tx = OLT_TX_NOMINAL + RNG.normal(0, 0.05)
            onu_rx = pon_tx - down_loss
            onu_tx = ONU_TX_NOMINAL + RNG.normal(0, 0.05)
            pon_rx = onu_tx - up_loss

            # BIP errors: very low normally; spike with bend / severe drift
            base_bip = max(0, RNG.normal(2, 1))
            if fault["type"] == "bend" and ts_idx >= fault["start_hour"]:
                base_bip += RNG.poisson(50)
            if fault["type"] == "drift" and onu_rx < -27:
                base_bip += RNG.poisson(20)

            # Temperature: vendor SFP, with mild daily cycle
            temp = 45 + 5 * np.sin(2 * np.pi * hour / 24) + RNG.normal(0, 1)
            bias = 35 + RNG.normal(0, 1.5)
            voltage = 3.3 + RNG.normal(0, 0.02)

            # Traffic counters (cumulative would be huge -> emit per-hour bytes)
            in_octets = int(traffic_mult * RNG.uniform(1e7, 5e7))
            out_octets = int(traffic_mult * RNG.uniform(2e7, 1e8))

            records.append(
                dict(
                    timestamp=ts,
                    olt_name=row.olt_name,
                    vendor=row.vendor,
                    model=row.model,
                    sitename=row.sitename,
                    ponport=row.ponport,
                    moduleclass=row.moduleclass,
                    l1_splitter=row.l1_splitter,
                    l2_splitter=row.l2_splitter,
                    ontid=row.ontid,
                    device_serial=row.device_serial,
                    circuit_id=row.circuit_id,
                    onu_uid=uid,
                    pon_txpwr=round(pon_tx, 3),
                    pon_rxpwr=round(pon_rx, 3),
                    pon_temp=round(temp, 2),
                    olt_bias_current=round(bias + 5, 2),
                    olt_voltage=round(voltage, 3),
                    olt_in_octets=in_octets,
                    olt_out_octets=out_octets,
                    olt_biperr=int(base_bip),
                    ranging=round(row.distance_m, 1),
                    onu_tx_power=round(onu_tx, 3),
                    onu_rx_power=round(onu_rx, 3),
                    onu_bias_current=round(bias, 2),
                    onu_voltage=round(voltage, 3),
                    onu_in_biperr=int(max(0, base_bip + RNG.normal(0, 1))),
                    onu_out_biperr=int(max(0, base_bip * 0.8 + RNG.normal(0, 1))),
                )
            )

    df = pd.DataFrame(records)
    return df


def main(out_dir: str = ".") -> None:
    os.makedirs(out_dir, exist_ok=True)
    print("Building topology...")
    topo = build_topology()
    print(f"  {len(topo)} ONUs across "
          f"{topo['olt_name'].nunique()} OLTs / "
          f"{topo['ponport'].nunique()} PON ports / "
          f"{topo['l2_splitter'].nunique()} L2 splitters")

    print("Planning anomalies...")
    plan = plan_anomalies(topo)
    fault_summary = pd.Series(
        [v["type"] for v in plan.values()]
    ).value_counts()
    print(fault_summary.to_string())

    print(f"Generating {HOURS} hours of telemetry...")
    ts = generate_timeseries(topo, plan)

    telem_path = os.path.join(out_dir, "telemetry.csv")
    plan_path = os.path.join(out_dir, "ground_truth.csv")
    topo_path = os.path.join(out_dir, "topology.csv")

    ts.to_csv(telem_path, index=False)
    topo.drop(columns=["base_down_loss", "base_up_loss"], errors="ignore") \
        .to_csv(topo_path, index=False)

    pd.DataFrame(
        [{"onu_uid": k, **v} for k, v in plan.items()]
    ).to_csv(plan_path, index=False)

    print(f"Wrote {telem_path}  ({len(ts):,} rows)")
    print(f"Wrote {topo_path}")
    print(f"Wrote {plan_path}")


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    main(out)
