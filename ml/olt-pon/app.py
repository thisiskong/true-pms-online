"""
FTTx ML Dashboard - Streamlit app.

Run:
    uv run python load_data.py data   # pull from PostgreSQL
    uv run python run_models.py data  # compute ML results
    uv run streamlit run app.py       # launch dashboard
"""

from __future__ import annotations

import os
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DATA_DIR  = os.environ.get("FTTX_DATA_DIR", "data")
DATA_PATH = os.path.join(DATA_DIR, "telemetry.parquet")

st.set_page_config(
    page_title="FTTx ML Dashboard",
    page_icon="\U0001F4E1",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading telemetry...")
def load_data(data_dir: str) -> pd.DataFrame:
    path = os.path.join(data_dir, "telemetry.parquet")
    if not os.path.exists(path):
        st.error(f"Telemetry not found at `{path}`. Run `python load_data.py data` first.")
        st.stop()
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=False)
    bad = int(df["timestamp"].isna().sum())
    if bad:
        st.warning(f"{bad:,} rows had unparseable timestamps and were dropped.")
        df = df.dropna(subset=["timestamp"]).reset_index(drop=True)
    return df


@st.cache_data(show_spinner="Loading ML results...")
def load_results(data_dir: str):
    missing = [
        f for f in ["results_drift", "results_budget", "results_bend", "results_health"]
        if not os.path.exists(os.path.join(data_dir, f"{f}.parquet"))
    ]
    if missing:
        st.error(
            f"ML results not found ({', '.join(missing)}). "
            f"Run `python run_models.py data` first."
        )
        st.stop()
    drift  = pd.read_parquet(os.path.join(data_dir, "results_drift.parquet"))
    budget = pd.read_parquet(os.path.join(data_dir, "results_budget.parquet"))
    bend   = pd.read_parquet(os.path.join(data_dir, "results_bend.parquet"))
    health = pd.read_parquet(os.path.join(data_dir, "results_health.parquet"))
    return drift, budget, bend, health


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
df = load_data(DATA_DIR)
drift, budget, bend, health = load_results(DATA_DIR)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("FTTx ML")
ts_min, ts_max = df["timestamp"].min(), df["timestamp"].max()
span_days = ((ts_max - ts_min).days + 1) if pd.notna(ts_min) and pd.notna(ts_max) else 0
st.sidebar.caption(
    f"Telemetry: {len(df):,} rows | "
    f"{df['onu_uid'].nunique()} ONUs | "
    f"{span_days} days"
)
sites = st.sidebar.multiselect(
    "Site filter",
    sorted(df["sitename"].unique()),
    default=sorted(df["sitename"].unique()),
)
olts = st.sidebar.multiselect(
    "OLT filter",
    sorted(df["olt_name"].unique()),
    default=sorted(df["olt_name"].unique()),
)

mask = df["sitename"].isin(sites) & df["olt_name"].isin(olts)
df_f = df[mask]
onus_f = set(df_f["onu_uid"].unique())

if df_f.empty:
    st.warning("No telemetry matches the current filters. "
               "Widen the Site or OLT selection in the sidebar.")
    st.stop()

# scope all detector outputs to the same filter
drift_f = drift[drift["onu_uid"].isin(onus_f)]
budget_f = budget[budget["onu_uid"].isin(onus_f)]
bend_f = bend[bend["onu_uid"].isin(onus_f)] if not bend.empty else bend
health_f = health[health["onu_uid"].isin(onus_f)]


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_overview, tab_anomalies, tab_topo, tab_budget, tab_bend, tab_onu = st.tabs(
    ["Overview", "Anomaly feed", "Topology", "Optical budget",
     "Bend detection", "ONU drill-down"]
)

# ----- Overview ------------------------------------------------------------
with tab_overview:
    st.header("Fleet overview")

    total_onu = len(onus_f)
    flagged_drift = int((drift_f["drift_z"] > 2).sum())
    flagged_budget = int(budget_f["flag"].sum())
    flagged_bend = int(bend_f["is_bend"].sum()) if not bend_f.empty else 0
    healthy = int((health_f["composite"] < 0.3).sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("ONUs in scope", f"{total_onu}")
    c2.metric("Healthy", f"{healthy}",
              delta=f"{healthy / total_onu * 100:.0f}%" if total_onu else "n/a")
    c3.metric("RxPower drift", flagged_drift, delta_color="inverse")
    c4.metric("Budget anomaly", flagged_budget, delta_color="inverse")
    c5.metric("Bend events", flagged_bend, delta_color="inverse")

    st.divider()

    st.subheader("RxPower distribution across the fleet (current hour)")
    latest_hr = df_f["timestamp"].max()
    title_ts = (latest_hr.strftime("%Y-%m-%d %H:%M")
                if pd.notna(latest_hr) else "latest snapshot")
    last_snap = df_f[df_f["timestamp"] == latest_hr] if pd.notna(latest_hr) else df_f
    fig = px.histogram(
        last_snap, x="onu_rx_power", nbins=40,
        color="sitename",
        title=f"Current ONU RxPower @ {title_ts}",
        labels={"onu_rx_power": "ONU RxPower (dBm)"},
    )
    fig.add_vline(x=-27, line_dash="dash", line_color="red",
                  annotation_text="Sensitivity floor")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Traffic across PON ports (24 h)")
    if pd.notna(latest_hr):
        last_day = df_f[df_f["timestamp"] >= latest_hr - pd.Timedelta(hours=24)]
    else:
        last_day = df_f
    traffic = (last_day.groupby(["timestamp", "ponport"])
                       [["olt_in_octets", "olt_out_octets"]]
                       .sum().reset_index())
    traffic["total_gbps"] = (traffic["olt_in_octets"] + traffic["olt_out_octets"]) * 8 / 1e9 / 3600
    fig2 = px.line(traffic, x="timestamp", y="total_gbps", color="ponport",
                   title="Aggregate PON port throughput",
                   labels={"total_gbps": "Throughput (Gbps, hourly avg)"})
    fig2.update_layout(showlegend=False)
    st.plotly_chart(fig2, use_container_width=True)


# ----- Anomaly feed --------------------------------------------------------
with tab_anomalies:
    st.header("Anomaly feed")
    st.caption("Composite health score - lower is worse. "
               "Click a row to investigate.")

    table = health_f.head(40).merge(
        df_f.drop_duplicates("onu_uid")[
            ["onu_uid", "olt_name", "ponport", "l1_splitter", "l2_splitter"]
        ],
        on="onu_uid", how="left",
    )
    table = table.merge(
        drift_f[["onu_uid", "reason"]].rename(columns={"reason": "drift_reason"}),
        on="onu_uid", how="left")
    table = table.merge(
        budget_f[["onu_uid", "reason"]].rename(columns={"reason": "budget_reason"}),
        on="onu_uid", how="left")
    if not bend_f.empty:
        table = table.merge(
            bend_f[["onu_uid", "reason"]].rename(columns={"reason": "bend_reason"}),
            on="onu_uid", how="left")
    else:
        table["bend_reason"] = "ok"

    table["primary_reason"] = table.apply(
        lambda r: next(
            (r[c] for c in ["drift_reason", "budget_reason", "bend_reason"]
             if isinstance(r.get(c), str) and r[c] != "ok"),
            "ok"
        ),
        axis=1,
    )

    display = table[
        ["onu_uid", "olt_name", "ponport", "l2_splitter",
         "health", "composite", "primary_reason",
         "drift_score", "budget_score", "bend_score"]
    ].rename(columns={
        "health": "Health (0-100)",
        "composite": "Risk score",
        "primary_reason": "Reason",
    })
    st.dataframe(
        display,
        use_container_width=True,
        height=600,
        column_config={
            "Risk score": st.column_config.ProgressColumn(
                "Risk score",
                help="Composite anomaly score (0 = clean, 1 = severe)",
                min_value=0.0, max_value=1.0,
                format="%.2f",
            ),
            "Health (0-100)": st.column_config.ProgressColumn(
                "Health",
                min_value=0, max_value=100,
                format="%.0f",
            ),
            "drift_score": st.column_config.NumberColumn(format="%.2f"),
            "budget_score": st.column_config.NumberColumn(format="%.2f"),
            "bend_score": st.column_config.NumberColumn(format="%.2f"),
        },
    )


# ----- Topology ------------------------------------------------------------
with tab_topo:
    st.header("Topology drill-down")
    st.caption("Treemap: OLT -> PON port -> L1 splitter -> L2 splitter -> ONU. "
               "Color = composite risk score.")

    topo = df_f.drop_duplicates("onu_uid")[
        ["onu_uid", "olt_name", "ponport", "l1_splitter", "l2_splitter"]
    ].merge(health_f[["onu_uid", "composite", "health"]], on="onu_uid")

    fig = px.treemap(
        topo,
        path=[px.Constant("Fleet"), "olt_name", "ponport",
              "l2_splitter", "onu_uid"],
        values=None,
        color="composite",
        color_continuous_scale="RdYlGn_r",
        range_color=[0, topo["composite"].max() or 1],
        title="Click to drill in",
    )
    fig.update_traces(root_color="lightgrey")
    fig.update_layout(margin=dict(t=40, b=10, l=10, r=10), height=700)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Splitter-group concentration of anomalies")
    splitter_summary = (topo.assign(
            unhealthy=(topo["composite"] > 0.4).astype(int))
        .groupby("l2_splitter")
        .agg(onus=("onu_uid", "nunique"),
             unhealthy=("unhealthy", "sum"),
             avg_risk=("composite", "mean"))
        .reset_index()
        .sort_values("avg_risk", ascending=False))
    splitter_summary["unhealthy_pct"] = (splitter_summary["unhealthy"] /
                                          splitter_summary["onus"] * 100)
    st.dataframe(splitter_summary.head(20), use_container_width=True)
    st.caption("High `unhealthy_pct` on a single splitter often means the "
               "fault is *upstream* of that splitter, not at individual ONUs.")


# ----- Optical budget ------------------------------------------------------
with tab_budget:
    st.header("Optical budget validation")
    st.write(
        "A regression model learns the *expected* downstream loss given "
        "distance and topology, then flags ONUs whose observed loss is "
        "more than +/-2.5 dB off. Useful for catching **mis-cabling**, bad "
        "splices, or wrong-model SFPs."
    )

    fig = px.scatter(
        budget_f,
        x="ranging", y="observed_down_loss",
        color="abs_residual",
        color_continuous_scale="Reds",
        hover_data=["onu_uid", "expected_down_loss", "residual_db",
                    "l2_splitter"],
        labels={
            "ranging": "Ranging (m)",
            "observed_down_loss": "Observed downstream loss (dB)",
            "abs_residual": "|residual|",
        },
        title="Observed loss vs distance - outliers indicate budget violation",
    )
    st.plotly_chart(fig, use_container_width=True)

    flagged = budget_f[budget_f["flag"]].sort_values(
        "score", ascending=False)
    st.subheader(f"{len(flagged)} budget / topology anomalies")
    st.caption("Includes both loss-residual outliers (bad splice / "
               "high attenuation) and ranging outliers within their "
               "L2 splitter group (likely mis-cabled).")
    st.dataframe(
        flagged[["onu_uid", "ponport", "l2_splitter", "ranging",
                 "ranging_dev_m", "observed_down_loss",
                 "expected_down_loss", "residual_db",
                 "severity", "reason"]]
        .rename(columns={"residual_db": "Residual (dB)",
                         "ranging_dev_m": "Delta vs siblings (m)"}),
        use_container_width=True,
    )


# ----- Bend detection ------------------------------------------------------
with tab_bend:
    st.header("Cable bending detection")
    st.write(
        "Macrobend events show a **sudden step-down** in RxPower. Because "
        "bend loss is *wavelength-dependent*, downstream (1490 nm) and "
        "upstream (1310 nm) wavelengths see different attenuation - so we "
        "confirm bends by checking that the downstream loss step is larger "
        "than the upstream step."
    )

    if bend_f.empty:
        st.info("No change-points detected.")
    else:
        fig = px.scatter(
            bend_f, x="rx_step_db", y="asymmetry_db",
            color="is_bend",
            color_discrete_map={True: "#d62728", False: "#1f77b4"},
            hover_data=["onu_uid", "change_timestamp"],
            labels={"rx_step_db": "RxPower step (dB, drop)",
                    "asymmetry_db": "Down-Up loss asymmetry (dB)"},
            title="A change-point is a bend if BOTH the step and the "
                  "asymmetry are large",
        )
        fig.add_vline(x=1.8, line_dash="dash", line_color="red")
        fig.add_hline(y=0.25, line_dash="dash", line_color="red")
        st.plotly_chart(fig, use_container_width=True)

        bends = bend_f[bend_f["is_bend"]].sort_values("score", ascending=False)
        st.subheader(f"{len(bends)} confirmed bend events")
        st.dataframe(
            bends[["onu_uid", "change_timestamp", "rx_step_db",
                   "down_step_db", "up_step_db", "asymmetry_db", "reason"]],
            use_container_width=True,
        )


# ----- ONU drill-down ------------------------------------------------------
with tab_onu:
    st.header("ONU drill-down")

    default_onu = (health_f.head(1)["onu_uid"].iloc[0]
                   if len(health_f) else None)
    onu_list = sorted(onus_f)
    onu_id = st.selectbox(
        "Pick an ONU",
        onu_list,
        index=onu_list.index(default_onu) if default_onu in onu_list else 0,
    )

    sub = df_f[df_f["onu_uid"] == onu_id].sort_values("timestamp")
    info = sub.iloc[0]

    c1, c2, c3 = st.columns(3)
    c1.write(f"**OLT** - {info['olt_name']}")
    c1.write(f"**PON** - {info['ponport']}")
    c2.write(f"**L1 splitter** - {info['l1_splitter']}")
    c2.write(f"**L2 splitter** - {info['l2_splitter']}")
    c3.write(f"**Vendor / model** - {info['vendor']} / {info['model']}")
    c3.write(f"**Ranging** - {info['ranging']:.0f} m")

    h = health_f[health_f["onu_uid"] == onu_id]
    if not h.empty:
        h = h.iloc[0]
        st.metric("Health score", f"{h['health']:.0f}/100",
                  delta=f"{h['composite']:.2f} risk")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=sub["timestamp"], y=sub["onu_rx_power"], name="ONU RxPower"))
    fig.add_trace(go.Scatter(
        x=sub["timestamp"], y=sub["pon_rxpwr"], name="OLT RxPower (upstream)"))
    fig.update_layout(title="Optical power",
                      yaxis_title="dBm", height=320)
    st.plotly_chart(fig, use_container_width=True)

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=sub["timestamp"], y=sub["pon_txpwr"] - sub["onu_rx_power"],
        name="Downstream loss"))
    fig2.add_trace(go.Scatter(
        x=sub["timestamp"], y=sub["onu_tx_power"] - sub["pon_rxpwr"],
        name="Upstream loss"))
    fig2.update_layout(title="Computed loss (asymmetry = bend signature)",
                       yaxis_title="dB", height=320)
    st.plotly_chart(fig2, use_container_width=True)

    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(
        x=sub["timestamp"], y=sub["onu_in_biperr"], name="BIP errors in"))
    fig3.add_trace(go.Scatter(
        x=sub["timestamp"], y=sub["pon_temp"], name="SFP temp C",
        yaxis="y2"))
    fig3.update_layout(
        title="Errors and temperature",
        yaxis=dict(title="BIP errors"),
        yaxis2=dict(title="C", overlaying="y", side="right"),
        height=320,
    )
    st.plotly_chart(fig3, use_container_width=True)
