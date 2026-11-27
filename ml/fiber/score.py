"""Stage 5: four sub-scores (0..1) -> fiber score 1..10 with caps and a confidence value."""

import numpy as np


def _interp(x, pts):
  x = np.asarray(x, dtype=float)
  xs, ys = zip(*pts)
  return np.where(np.isnan(x), np.nan, np.interp(x, xs, ys))


def _fmin(*arrays):
  out = arrays[0]
  for a in arrays[1:]:
    out = np.fmin(out, a)   # ignores NaN unless both are NaN
  return out


def _col(f, name):
  return f[name].to_numpy(dtype=float, na_value=np.nan)


def score(f, cfg, window):
  """Adds s_power, s_excess, s_error, s_stability, score, conf to f (in place)."""
  sc = cfg["score"]
  min_days = cfg["min_days_for_trend"]

  rx_med, rx_p10 = _col(f, "rx_med"), _col(f, "rx_p10")
  s_med = _interp(rx_med, sc["power"])
  s_p10 = _interp(rx_p10, sc["power"])
  f["s_power"] = np.where(np.isnan(s_p10), s_med, (s_med + s_p10) / 2)

  f["s_excess"] = _interp(_col(f, "excess_loss"), sc["excess"])

  bip_obs, bip_days = _col(f, "bip_obs"), _col(f, "bip_days")
  s_mag = _interp(_col(f, "bip_log_mean"), sc["error_mag"])
  with np.errstate(invalid="ignore", divide="ignore"):
    bip_share = np.where(bip_obs >= min_days, bip_days / bip_obs, np.nan)
  s_freq = _interp(bip_share, sc["error_freq"])
  f["s_error"] = _fmin(s_mag, s_freq)

  s_sd = _interp(_col(f, "rx_sd"), sc["rx_sd"])
  s_slope = _interp(_col(f, "rx_slope"), sc["rx_slope"])
  lc = np.where(_col(f, "lc_obs") > 0, _col(f, "lc_mean"), np.nan)
  s_lc = _interp(lc, sc["lostcarrier"])
  f["s_stability"] = _fmin(s_sd, s_slope, s_lc)

  weights = sc["weights"]
  num = np.zeros(len(f))
  den = np.zeros(len(f))
  for name, w in weights.items():
    s = f[f"s_{name}"].to_numpy(dtype=float)
    present = ~np.isnan(s)
    num += np.where(present, w * s, 0.0)
    den += np.where(present, w, 0.0)

  with np.errstate(invalid="ignore", divide="ignore"):
    S = np.where(den > 0, num / den, np.nan)
  out = np.round(1 + 9 * S)

  for cap in sc["caps"]:
    out = np.where(rx_med < cap["rx_below"], np.fmin(out, cap["max_score"]), out)
  every_day = (bip_obs >= min_days) & (bip_days == bip_obs)
  out = np.where(every_day, np.fmin(out, sc["bip_every_day_max_score"]), out)

  f["score"] = out
  f["score"] = f["score"].astype("Int8")
  coverage = np.minimum(1.0, _col(f, "days_obs") / window)
  f["conf"] = np.round(den / sum(weights.values()) * coverage, 3)
  return f
