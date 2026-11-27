"""Stage 4: learn expected Rx from the ONU's path, then compute excess_loss = expected_rx - rx_med.

Training is the slow part of a run, so the model is retrained only when needed (see load_or_train):
daily runs load the newest saved model and only predict.
"""

import datetime as dt
import json
import re
import zlib

import lightgbm as lgb
import numpy as np

from common import ROOT, log, ymd

MODELS = ROOT / "models"


def _pon_bucket(df, n=1000):
  key = (df["device"].astype(str) + "|" + df["ponport"].astype(str)).to_numpy()
  return np.fromiter((zlib.crc32(k.encode()) % n for k in key), dtype=np.int32, count=len(key))


def _prepare(f, cfg):
  m = cfg["model"]
  cats = m["categorical"]
  X = f[cats + m["numeric"]].copy()
  for c in cats:
    X[c] = X[c].fillna("unknown").astype("category")
  # "Presumed healthy" ONUs: they define what normal loss looks like.
  healthy = (
    f["rx_med"].notna() & ~f["dq_no_odn"] & ~f["dq_topo_mismatch"] & ~f["hw_flag"]
    & (f["bip_days"].fillna(0) == 0) & f["len_km"].notna() & f["split_db"].notna()
  ).to_numpy()
  # Held out by PON port (stable hash), so the model cannot memorise one port's OLT optic.
  holdout = _pon_bucket(f) < int(m["holdout_share"] * 1000)
  return X, healthy, holdout


def _train(X, y, healthy, holdout, cfg):
  m = cfg["model"]
  cats = m["categorical"]
  tr, va = healthy & ~holdout, healthy & holdout
  log(f"expected-rx model: training on {tr.sum():,} ONUs, holdout {va.sum():,} (by PON port)")
  dtr = lgb.Dataset(X[tr], y[tr], categorical_feature=cats)
  dva = lgb.Dataset(X[va], y[va], categorical_feature=cats, reference=dtr)
  model = lgb.train(
    m["params"], dtr, num_boost_round=m["num_boost_round"], valid_sets=[dva], valid_names=["holdout"],
    callbacks=[lgb.early_stopping(m["early_stopping_rounds"], verbose=False), lgb.log_evaluation(0)],
  )
  gain = model.feature_importance("gain")
  feats = list(X.columns)
  return model, {
    "train_onus": int(tr.sum()), "holdout_onus": int(va.sum()),
    "best_iteration": int(model.best_iteration),
    "baseline_mae_db": round(float(np.mean(np.abs(np.median(y[tr]) - y[va]))), 3),
    "feature_importance_gain": {
      k: round(float(v) / gain.sum(), 4) for k, v in sorted(zip(feats, gain), key=lambda t: -t[1])
    },
  }


def _latest_model(d, max_age_days):
  """Newest saved model trained on or before d and at most max_age_days old: (path, date) or (None, None)."""
  best = (None, None)
  for p in MODELS.glob("expected_rx_*.txt"):
    mt = re.fullmatch(r"expected_rx_(\d{8})\.txt", p.name)
    if not mt:
      continue
    md = dt.datetime.strptime(mt.group(1), "%Y%m%d").date()
    if md <= d and (d - md).days <= max_age_days and (best[1] is None or md > best[1]):
      best = (p, md)
  return best


def load_or_train(f, cfg, d, retrain=False):
  """Adds expected_rx and excess_loss to f (in place). Returns a metrics dict.

  Reuses the newest model at most model.max_age_days old unless retrain is set. Each run also
  measures holdout MAE on today's data, so a reused model that has drifted shows up.
  """
  m = cfg["model"]
  X, healthy, holdout = _prepare(f, cfg)
  y = f["rx_med"].to_numpy()
  path, model_date = (None, None) if retrain else _latest_model(d, m["max_age_days"])

  if path is None:
    model, metrics = _train(X, y, healthy, holdout, cfg)
    MODELS.mkdir(parents=True, exist_ok=True)
    path, model_date = MODELS / f"expected_rx_{ymd(d)}.txt", d
    model.save_model(str(path), num_iteration=model.best_iteration)
    metrics["trained_now"] = True
  else:
    model = lgb.Booster(model_file=str(path))
    meta = path.with_suffix(".json")
    metrics = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
    metrics["trained_now"] = False
    log(f"expected-rx model: reusing {path.name} (trained {model_date}, {(d - model_date).days} day(s) old)")

  pred = model.predict(X, num_iteration=model.best_iteration if metrics["trained_now"] else None)
  va = healthy & holdout
  mae = round(float(np.mean(np.abs(pred[va] - y[va]))), 3)
  metrics.update({"model_file": path.name, "model_date": model_date.isoformat(), "holdout_mae_db": mae})

  if metrics["trained_now"]:
    metrics["trained_mae_db"] = mae
    path.with_suffix(".json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    log(f"expected-rx model: holdout MAE {mae:.2f} dB (median baseline {metrics['baseline_mae_db']:.2f} dB), "
        f"{metrics['best_iteration']} trees -> {path.name}")
  else:
    drift = mae - metrics.get("trained_mae_db", mae)
    metrics["mae_drift_db"] = round(drift, 3)
    msg = f"expected-rx model: holdout MAE today {mae:.2f} dB ({drift:+.2f} dB vs training)"
    if drift > m["max_mae_drift_db"]:
      msg += f" - above the {m['max_mae_drift_db']} dB drift limit; run with --retrain"
    log(msg)

  # No topology or no path data: no meaningful expectation.
  usable = (~f["dq_no_odn"] & f["len_km"].notna() & f["split_db"].notna()).to_numpy()
  f["expected_rx"] = np.where(usable, pred, np.nan)
  f["excess_loss"] = f["expected_rx"] - f["rx_med"]
  return metrics
