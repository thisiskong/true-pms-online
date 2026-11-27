"""Stage 6: localise bad ONUs to the device, L1 or L2 that best explains them.

Every bad ONU is attributed to the highest level that explains it, checked top-down:
device -> L1 -> L2 -> drop/ONU. That way one bad feeder shows up once, as an L1, not as many L2s.
"""

import numpy as np
import pandas as pd
from scipy.stats import binom


def _stats(g, p0, alpha):
  g["bad_share"] = g["n_bad"] / g["n_onu"]
  g["bad_rate_shrunk"] = (g["n_bad"] + alpha * p0) / (g["n_onu"] + alpha)
  # P(X >= n_bad) when each ONU is bad with the global rate p0.
  g["p_value"] = binom.sf(g["n_bad"] - 1, g["n_onu"], p0)
  return g


def attribute(con, f, cfg):
  a = cfg["attribution"]
  alpha = a["shrink_alpha"]
  scored = f["score"].notna()
  f["bad"] = (f["score"] <= a["bad_score"]).fillna(False).astype(bool)
  p0 = float(f.loc[scored, "bad"].mean())

  con.register("onu", f[scored & f["l1name"].notna()])

  # --- L2 (excluding L2 names that appear under several devices) ---
  g2 = con.execute("""
    with g as (
      select device, l1name, l2name, count(*) as n_onu, count_if(bad) as n_bad,
        median(rx_med) as med_rx, median(excess_loss) as med_excess_loss,
        median(excess_loss) filter (where bad) as med_excess_bad
      from onu where l2name is not null and not dq_l2_multi_device
      group by all
    ),
    sib as (
      select a.device, a.l1name, a.l2name, median(b.med_rx) as sib_med, count(*) as n_sib
      from g a join g b on a.device = b.device and a.l1name = b.l1name and a.l2name <> b.l2name
      group by all
    )
    select g.*, g.med_rx - sib.sib_med as med_peer_delta, coalesce(sib.n_sib, 0) as n_sibling_l2
    from g left join sib using (device, l1name, l2name)
  """).df()
  g2 = _stats(g2, p0, alpha)
  r = a["l2"]
  g2["suspect"] = (
    (g2["n_bad"] >= r["min_bad"]) & (g2["p_value"] <= r["max_p"])
    & ((g2["bad_share"] >= r["min_bad_share"]) | (g2["med_peer_delta"] <= r["max_peer_delta"]))
  )

  # --- L1 (~ PON port) ---
  g1 = con.execute("""
    with g as (
      select device, l1name, count(*) as n_onu, count_if(bad) as n_bad,
        count(distinct l2name) as n_l2, count(distinct l2name) filter (where bad) as n_bad_l2,
        median(rx_med) as med_rx, median(excess_loss) as med_excess_loss,
        median(excess_loss) filter (where bad) as med_excess_bad
      from onu group by all
    ),
    sib as (
      select a.device, a.l1name, median(b.med_rx) as sib_med, count(*) as n_sib
      from g a join g b on a.device = b.device and a.l1name <> b.l1name
      group by all
    )
    select g.*, g.med_rx - sib.sib_med as med_peer_delta, coalesce(sib.n_sib, 0) as n_sibling_l1
    from g left join sib using (device, l1name)
  """).df()
  g1 = _stats(g1, p0, alpha)
  r = a["l1"]
  g1["suspect"] = (
    (g1["n_onu"] >= r["min_onu"]) & (g1["n_bad"] >= r["min_bad"]) & (g1["p_value"] <= r["max_p"])
    & (g1["bad_rate_shrunk"] >= r["min_shrunk_rate"])
    & ((g1["n_bad_l2"] >= r["min_bad_l2"]) | (g1["n_l2"] <= 1))
  )

  # --- device ---
  gd = con.execute("""
    select device, any_value(vendor) as vendor, any_value(model) as model,
      count(*) as n_onu, count_if(bad) as n_bad, count(distinct l1name) as n_l1,
      median(rx_med) as med_rx, median(excess_loss) as med_excess_loss,
      median(excess_loss) filter (where bad) as med_excess_bad
    from onu group by all
  """).df()
  con.unregister("onu")
  gd["med_peer_delta"] = gd["med_rx"] - gd["med_rx"].median()
  gd = _stats(gd, p0, alpha)
  sus_l1 = g1.groupby("device")["suspect"].sum().rename("n_suspect_l1")
  gd = gd.merge(sus_l1, on="device", how="left").fillna({"n_suspect_l1": 0})
  r = a["device"]
  gd["suspect"] = (
    (gd["n_l1"] >= r["min_l1"]) & (gd["n_suspect_l1"] / gd["n_l1"] >= r["min_suspect_l1_share"])
    & (gd["p_value"] <= r["max_p"])
  )

  # --- top-down attribution per bad ONU ---
  f = f.merge(gd.loc[gd["suspect"], ["device"]].assign(_dev=True), on="device", how="left")
  f = f.merge(g1.loc[g1["suspect"], ["device", "l1name"]].assign(_l1=True), on=["device", "l1name"], how="left")
  f = f.merge(
    g2.loc[g2["suspect"], ["device", "l1name", "l2name"]].assign(_l2=True),
    on=["device", "l1name", "l2name"], how="left",
  )
  dev, l1, l2 = (f[c].fillna(False).astype(bool) for c in ("_dev", "_l1", "_l2"))
  f["attributed_to"] = np.select(
    [~f["bad"], dev, l1, l2, f["hw_flag"]],
    [None, "device", "l1", "l2", "onu_hw"],
    default="drop",
  )
  f["attributed_to"] = f["attributed_to"].where(f["bad"], None)
  f = f.drop(columns=["_dev", "_l1", "_l2"])

  # --- suspect lists, ranked by impact ---
  def finish(g, level, keys):
    att = (f[f["attributed_to"] == level].groupby(keys).size().rename("n_bad_attributed").reset_index())
    g = g[g["suspect"]].merge(att, on=keys, how="left").fillna({"n_bad_attributed": 0})
    g["n_bad_attributed"] = g["n_bad_attributed"].astype(int)
    # impact = ONUs affected x (1 + dB of excess loss on the bad ONUs); stays > 0 when there is no model value.
    g["impact"] = g["n_bad_attributed"] * (1 + g["med_excess_bad"].clip(lower=0).fillna(0))
    g = g[g["n_bad_attributed"] > 0].drop(columns=["suspect"])
    return g.sort_values("impact", ascending=False).reset_index(drop=True)

  suspects = {
    "device": finish(gd, "device", ["device"]),
    "l1": finish(g1, "l1", ["device", "l1name"]),
    "l2": finish(g2, "l2", ["device", "l1name", "l2name"]),
  }
  summary = {
    "global_bad_rate": round(p0, 5),
    "bad_onus": int(f["bad"].sum()),
    "attributed": {k: int(v) for k, v in f["attributed_to"].value_counts().items()},
    "suspects": {k: len(v) for k, v in suspects.items()},
  }
  return f, suspects, summary
