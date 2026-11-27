"""Fiber score pipeline: ingest -> cleanse -> features -> expected-loss model -> score -> attribution.

Usage (from ml/):
  uv run fiber/run.py --date 2026-11-20               # 7-day window ending on that date
  uv run fiber/run.py --date 2026-11-20 --window 30
  uv run fiber/run.py --date 2026-11-20 --force       # rebuild the lake parquet for the window
  uv run fiber/run.py --date 2026-11-20 --retrain     # retrain the model (default: reuse one up to 7 days old)

Reads  data/onu_pon_1d_YYYYMMDD.jsonl and data/odn_onu.jsonl (from export_jsonl.py).
Writes out/onu_fiber_score_YYYYMMDD.parquet, out/suspect_{device,l1,l2}_YYYYMMDD.csv,
       out/dq_report_YYYYMMDD.json; models/expected_rx_YYYYMMDD.{txt,json} when it trains
"""

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from attribute import attribute  # noqa: E402
from cleanse import METRIC_FIELDS, cleanse_metrics, cleanse_odn  # noqa: E402
from common import OUT, connect, load_cfg, log, part, sql_path, ymd  # noqa: E402
from expected_loss import load_or_train  # noqa: E402
from features import build_features, window_dates  # noqa: E402
from ingest import ingest, ingest_undated_odn, lake_dates  # noqa: E402
from score import score  # noqa: E402

ONU_COLUMNS = [
  "device", "ponport", "ontid", "vendor", "model", "moduleclass", "l1name", "l2name",
  "score", "conf", "s_power", "s_excess", "s_error", "s_stability",
  "rx_med", "rx_p10", "rx_sd", "rx_slope", "rx_margin", "overload",
  "expected_rx", "excess_loss", "peer_delta_l2", "peer_n_l2", "peer_delta_l1",
  "bip_days", "bip_obs", "bip_log_mean", "bip_out_log_mean", "lc_days", "lc_mean",
  "len_km", "split_db", "splitratio", "l1ratio", "l2ratio", "ranging", "range_mismatch",
  "days_obs", "hw_flag", "hw_days",
  "tx_med", "tx_obs", "hw_tx_days", "voltage_med", "voltage_obs", "hw_voltage_days",
  "temp_med", "temp_obs", "hw_temp_days", "current_med", "current_obs", "hw_current_days",
  "dq_no_odn", "dq_topo_mismatch", "dq_l2_multi_device",
  "bad", "attributed_to",
]


def latest_odn(con, d, cfg, force):
  """Pick the ODN snapshot for d: the latest one on or before d, else the earliest one after d.

  Sources: the undated data/odn_onu.jsonl (filed under its export date), legacy dated
  data/odn_onu_YYYYMMDD.jsonl files, and snapshots already in the lake.
  """
  ingest_undated_odn(con, force)
  for i in range(31):
    ingest(con, "odn_onu", d - dt.timedelta(days=i), force)   # legacy dated files, if any
  dates = lake_dates("odn_onu")
  if not dates:
    raise SystemExit("no odn_onu snapshot: run export_jsonl.py first")
  before = [x for x in dates if x <= d]
  x = before[-1] if before else dates[0]
  if not before:
    log(f"warning: no ODN snapshot on or before {d}; using the next one, {x}")
  cleanse_odn(con, x, cfg, force)
  return x, part("clean_odn", x)


def dq_report(con, dates, f):
  files = "[" + ", ".join(sql_path(part("clean_onu", x)) for x in dates) + "]"
  parts = []
  for n in METRIC_FIELDS:
    parts.append(f"count_if(dq_{n} = 'sentinel') as {n}__sentinel")
    parts.append(f"count_if(dq_{n} = 'range') as {n}__range")
    parts.append(f"count({n}) as {n}__valid")
  rows = con.execute(f"""
    select coalesce(vendor, '(none)') as vendor, count(*) as rows, count_if(fix_voltage) as voltage__unit_fix,
      count_if(hw_flag) as hw_flag_days, {", ".join(parts)}
    from read_parquet({files}) group by 1 order by rows desc
  """).df()
  by_vendor = {}
  for rec in rows.to_dict("records"):
    v = rec.pop("vendor")
    out = {"rows": int(rec.pop("rows"))}
    for k, val in rec.items():
      field, kind = k.split("__") if "__" in k else (k, None)
      out.setdefault(field, {})[kind or "count"] = 0 if val != val else int(val)   # NaN when a vendor has no values
    by_vendor[v] = out
  return {
    "days": [x.isoformat() for x in dates],
    "onus": len(f),
    "by_vendor": by_vendor,
    "join": {
      "no_odn": int(f["dq_no_odn"].sum()),
      "topology_mismatch": int(f["dq_topo_mismatch"].sum()),
      "l2_multi_device": int(f["dq_l2_multi_device"].sum()),
      "range_mismatch": int(f["range_mismatch"].fillna(False).sum()),
    },
  }


def main():
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--date", type=dt.date.fromisoformat, default=dt.date.today() - dt.timedelta(days=1))
  ap.add_argument("--window", type=int, default=7, help="days in the scoring window (default 7)")
  ap.add_argument("--force", action="store_true", help="rebuild lake parquet even if it exists")
  ap.add_argument("--retrain", action="store_true", help="retrain the expected-Rx model even if a recent one exists")
  args = ap.parse_args()
  d, window = args.date, args.window
  started = time.monotonic()
  cfg = load_cfg()
  con = connect()
  OUT.mkdir(parents=True, exist_ok=True)

  # Stages 0-1 for every day in the window that has raw data.
  for i in range(window):
    x = d - dt.timedelta(days=i)
    if ingest(con, "onu_pon_1d", x, args.force):
      cleanse_metrics(con, x, cfg, args.force)
  odn_date, odn_path = latest_odn(con, d, cfg, args.force)
  log(f"odn snapshot {odn_date}")

  # Stages 2-3.
  f = build_features(con, d, window, odn_path, cfg)
  dates = window_dates(d, window)
  if len(dates) < cfg["min_days_for_trend"]:
    log(f"single/short-window mode: {len(dates)} day(s); rx_sd, rx_slope and bip frequency are skipped")

  # Stage 4: reuses a recent saved model unless --retrain (training is most of a run's time).
  model_metrics = load_or_train(f, cfg, d, retrain=args.retrain)

  # Stages 5-6.
  score(f, cfg, window)
  f, suspects, attr_summary = attribute(con, f, cfg)

  # Outputs.
  f[ONU_COLUMNS].to_parquet(OUT / f"onu_fiber_score_{ymd(d)}.parquet", index=False)
  for level, g in suspects.items():
    g.to_csv(OUT / f"suspect_{level}_{ymd(d)}.csv", index=False, float_format="%.4g")

  hist = f["score"].value_counts().sort_index()
  report = dq_report(con, dates, f)
  report.update({
    "run_date": d.isoformat(), "window": window, "odn_date": odn_date.isoformat(),
    "model": model_metrics,
    "score_histogram": {int(k): int(v) for k, v in hist.items()},
    "unscored_onus": int(f["score"].isna().sum()),
    "mean_conf": round(float(np.nanmean(f["conf"])), 3),
    "attribution": attr_summary,
  })
  with open(OUT / f"dq_report_{ymd(d)}.json", "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=2)

  total = int(hist.sum())
  log("score histogram: " + "  ".join(f"{k}:{v / total:.1%}" for k, v in hist.items()))
  log(f"bad (score <= {cfg['attribution']['bad_score']}): {attr_summary['bad_onus']:,} "
      f"-> {attr_summary['attributed']}")
  log(f"suspects: {attr_summary['suspects']}")
  log(f"done in {time.monotonic() - started:.0f}s -> {OUT}")


if __name__ == "__main__":
  main()
