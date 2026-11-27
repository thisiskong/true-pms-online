"""Fiber score pipeline: cleanse -> features -> expected-loss model -> score -> attribution.

Runs are weekly, Monday-Sunday, dated by the Sunday (the UI labels them as ISO weeks, e.g. 2026-W47).

Usage (from ml/):
  uv run fiber/run.py                                 # last complete week: Monday-Sunday ending last Sunday
  uv run fiber/run.py --date 2026-11-22               # the week ending on that Sunday (other dates: ad-hoc 7-day window)
  uv run fiber/run.py --date 2026-11-22 --window 30
  uv run fiber/run.py --date 2026-11-22 --force       # re-cleanse the window (clean_onu / clean_odn)
  uv run fiber/run.py --date 2026-11-22 --retrain     # retrain the model (default: reuse one up to 7 days old)

Reads  lake/onu_pon_1d/date=*/part.parquet and lake/odn_onu/date=*/part.parquet, written straight from
       Postgres by fiber/export.py. Run that first: a window with days missing from the lake is refused
       (--allow-partial scores it anyway, without those days).
Writes out/onu_fiber_score_YYYYMMDD.parquet, out/suspect_{device,l1,l2}_YYYYMMDD.parquet,
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
from common import OUT, connect, lake_dates, load_cfg, log, part, sql_path, ymd  # noqa: E402
from expected_loss import load_or_train  # noqa: E402
from features import build_features, window_dates  # noqa: E402
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
  """Pick the lake ODN snapshot for d: the latest one on or before d, else the earliest one after d."""
  dates = lake_dates("odn_onu")
  if not dates:
    raise SystemExit("no odn_onu snapshot: run `uv run fiber/export.py odn_onu` first")
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


def last_sunday(today=None):
  """The Sunday that ends the last complete Monday-Sunday week. On a Sunday that is the previous Sunday,
  because the day's data is only exported the next day."""
  today = today or dt.date.today()
  return today - dt.timedelta(days=(today.weekday() + 1) % 7 or 7)


def main():
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--date", type=dt.date.fromisoformat, default=None,
                  help="last day of the window (default: last Sunday, i.e. the last complete Monday-Sunday week)")
  ap.add_argument("--window", type=int, default=7, help="days in the scoring window (default 7)")
  ap.add_argument("--force", action="store_true", help="re-cleanse lake parquet (clean_onu / clean_odn) even if it exists")
  ap.add_argument("--retrain", action="store_true", help="retrain the expected-Rx model even if a recent one exists")
  ap.add_argument("--allow-partial", action="store_true",
                  help="score the window even if some days are missing from the lake (default: refuse)")
  args = ap.parse_args()
  d, window = args.date or last_sunday(), args.window
  if window == 7 and d.weekday() != 6:
    log(f"note: {d} is a {d:%A}, so this is an ad-hoc run, not a Monday-Sunday week")
  log(f"run {d}, window {d - dt.timedelta(days=window - 1)} .. {d}")
  started = time.monotonic()
  cfg = load_cfg()
  # A run must cover its whole window: check the lake before doing any work.
  days = [d - dt.timedelta(days=i) for i in range(window - 1, -1, -1)]
  missing = [x for x in days if not part("onu_pon_1d", x).exists()]
  if missing:
    fix = f"uv run fiber/export.py onu_pon_1d --start {missing[0]} --end {missing[-1]}"
    msg = f"{len(missing)} of {window} day(s) not in the lake: {', '.join(x.isoformat() for x in missing)}"
    if not args.allow_partial:
      raise SystemExit(f"refusing to score an incomplete window: {msg}\n"
                       f"  export them first: {fix}\n"
                       f"  (or pass --allow-partial to score without them)")
    log(f"warning: --allow-partial, scoring without {msg}")

  con = connect()
  OUT.mkdir(parents=True, exist_ok=True)

  # Stage 1 for every day in the window.
  for x in days:
    if x not in missing:
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
    # Typed, full precision. People get CSV from the backend's /api/fiber/suspects.csv.
    g.to_parquet(OUT / f"suspect_{level}_{ymd(d)}.parquet", index=False)

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
