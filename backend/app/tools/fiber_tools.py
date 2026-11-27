"""Fiber-score tools (read-only) for the shared registry: chat + MCP.

Data comes from the ml/fiber batch output via app.queries.fiber. Scores are 1 (poor) to 10 (excellent).
"""
from functools import wraps
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.queries import devices, fiber

# Mirrors ml/fiber/ranges.yaml (score.weights, score.caps, bip_every_day_max_score). Keep in sync,
# like frontend/src/components/fiber/score.tsx.
WEIGHTS = {"power": 0.40, "excess": 0.25, "error": 0.20, "stability": 0.15}
CAPS = ((-30.0, 1), (-28.0, 3))  # rx_med below -> max score (strictest first)
BIP_EVERY_DAY_MAX = 5
MIN_DAYS_FOR_TREND = 3
NO_BIP_VENDORS = ("GCOM", "Raisecom")
TARGET_MAE_DB = 1.5

DATE_DESC = "Run date YYYY-MM-DD; default = latest run"
DATE_RE = r"^\d{4}-?\d{2}-?\d{2}$"


class FiberError(ValueError):
  """A ValueError, so the registry turns it into a model-correctable ToolInputError."""


class _In(BaseModel):
  model_config = ConfigDict(extra="forbid")


class _Dev(_In):
  device_id: int | None = Field(None, description="OLT device id (preferred)")
  device: str | None = Field(None, max_length=120, description="Exact OLT name, e.g. AYT06004GO0")


class FiberOverviewIn(_In):
  date: str | None = Field(None, pattern=DATE_RE, description=DATE_DESC)


class FiberSuspectsIn(_In):
  level: Literal["l2", "l1", "device"] = Field(
    "l2", description="l2 = L2 splitter segment, l1 = L1 feeder / PON port, device = whole OLT")
  region: str | None = Field(None, max_length=50, description="Exact region")
  province: str | None = Field(None, max_length=80, description="Exact province (Thai name, as in the device table)")
  vendor: str | None = Field(None, max_length=50, description="Exact OLT vendor")
  q: str | None = Field(None, max_length=100, description="Substring of OLT, L1, L2 or site name")
  sort: Literal["impact", "n_bad", "bad_share", "med_excess_loss"] = Field(
    "impact", description="Sorted descending; impact = expected field-work payoff (default)")
  limit: int = Field(20, ge=1, le=50, description="Max rows (1-50)")
  date: str | None = Field(None, pattern=DATE_RE, description=DATE_DESC)


class FiberTreeIn(_Dev):
  only_bad: bool = Field(True, description="Only PON ports / L2 segments with at least one bad ONU")
  limit: int = Field(30, ge=1, le=100, description="Max PON ports, worst first")
  date: str | None = Field(None, pattern=DATE_RE, description=DATE_DESC)


class FiberOnusIn(_Dev):
  ponport: str | None = Field(None, max_length=40, description="PON port, e.g. 0-0-1-3")
  l1name: str | None = Field(None, max_length=80, description="Exact L1 name")
  l2name: str | None = Field(None, max_length=80, description="Exact L2 name")
  max_score: int | None = Field(4, ge=1, le=10, description="Only ONUs at or below this score (default 4 = bad); null = all")
  limit: int = Field(30, ge=1, le=100, description="Max rows, worst score first")
  date: str | None = Field(None, pattern=DATE_RE, description=DATE_DESC)


class OnuScoreIn(_Dev):
  ponport: str = Field(..., max_length=40, description="PON port, e.g. 0-0-0-1")
  ontid: str = Field(..., max_length=20, description="ONT id on that port")
  date: str | None = Field(None, pattern=DATE_RE, description=DATE_DESC)


async def _device_id(a: _Dev) -> int:
  if a.device_id is not None:
    if await fiber.device_name(a.device_id) is None:
      raise FiberError(f"device_id {a.device_id} not found")
    return a.device_id
  if not a.device:
    raise FiberError("give device_id or device (exact OLT name)")
  rows = await devices.find_devices_by_key(name=a.device)
  if not rows:
    raise FiberError(f"no device named exactly '{a.device}'; use search_devices to find it")
  return rows[0].id


def _run_errors(fn):
  @wraps(fn)
  async def wrapped(a):
    try:
      return await fn(a)
    except fiber.RunNotFound as e:
      raise FiberError(f"{e}; call fiber_overview for the latest run") from e
  return wrapped


@_run_errors
async def fiber_overview(a: FiberOverviewIn) -> dict:
  s = fiber.summary(a.date)
  m = s["model"]
  return {
    "date": s["date"], "window": s["window"], "days": len(s["days"]), "mean_conf": s["mean_conf"],
    "onus_scored": s["onus"], "unscored_onus": s["unscored_onus"],
    "bad_threshold": s["bad_threshold"], "bad_onus": s["bad_onus"], "global_bad_rate": s["global_bad_rate"],
    "score_histogram": s["histogram"],
    "bad_onus_attributed_to": s["attributed"], "suspect_counts": s["suspects"],
    "model": {"holdout_mae_db": m.get("holdout_mae_db"), "target_mae_db": TARGET_MAE_DB,
              "mae_drift_db": m.get("mae_drift_db"), "model_date": m.get("model_date"),
              "feature_importance_gain": m.get("feature_importance_gain")},
    "previous_run": s["prev"],
  }


SUSPECT_KEEP = (
  "device", "device_id", "l1name", "l2name", "vendor", "model", "region", "province", "sitename",
  "n_onu", "n_bad", "n_l1", "n_l2", "n_bad_l2", "n_suspect_l1", "n_sibling_l1", "n_sibling_l2",
  "bad_share", "bad_rate_shrunk", "med_rx", "med_excess_loss", "med_peer_delta", "impact",
)


@_run_errors
async def list_fiber_suspects(a: FiberSuspectsIn) -> dict:
  r = await fiber.suspects(a.date, a.level, a.region, a.province, a.vendor, a.q, a.sort, "desc", 1, a.limit)
  items = [{k: row[k] for k in SUSPECT_KEEP if k in row} for row in r["items"]]
  out = {"date": r["date"], "level": a.level, "items": items, "total": r["total"], "truncated": r["total"] > len(items)}
  if a.level == "l1":
    out["note"] = "L1 maps 1:1 to the PON port, so an L1 suspect may be the OLT PON optic rather than feeder fiber."
  return out


@_run_errors
async def fiber_device_tree(a: FiberTreeIn) -> dict:
  did = await _device_id(a)
  t = await fiber.device_tree(a.date, did)
  if t is None:
    raise FiberError(f"device_id {did} not found")
  ports = t.pop("items")
  if a.only_bad:
    ports = [{**p, "l2": [x for x in p["l2"] if x["n_bad"]]} for p in ports if p["n_bad"]]
  ports.sort(key=lambda p: (-p["n_bad"], -(p["n_bad"] / p["n_onu"] if p["n_onu"] else 0)))
  shown = ports[: a.limit]
  return {**t, "items": shown, "truncated": t["truncated"] or len(ports) > len(shown)}


@_run_errors
async def list_fiber_onus(a: FiberOnusIn) -> dict:
  did = await _device_id(a)
  r = await fiber.device_onus(a.date, did, a.ponport, a.l1name, a.l2name, a.max_score, "score", "asc", 1, a.limit)
  if r is None:
    raise FiberError(f"device_id {did} not found")
  return {**r, "device_id": did, "truncated": r["total"] > len(r["items"])}


def explain(o: dict[str, Any]) -> dict[str, Any]:
  """Why an ONU got its score: effective weights (missing sub-scores redistribute), caps, flags."""
  present = {k: o[f"s_{k}"] for k in WEIGHTS if o.get(f"s_{k}") is not None}
  wsum = sum(WEIGHTS[k] for k in present) or 1.0
  subs = {k: {"sub_score": round(present[k], 3) if k in present else None, "weight": WEIGHTS[k],
              "effective_weight": round(WEIGHTS[k] / wsum, 3) if k in present else 0.0} for k in WEIGHTS}
  weighted = sum(v * WEIGHTS[k] / wsum for k, v in present.items()) if present else None
  caps = []
  rx = o.get("rx_med")
  for below, mx in CAPS:
    if rx is not None and rx < below:
      caps.append(f"rx_med {rx:.1f} dBm is below {below:.0f} dBm, so the score is capped at {mx}")
      break
  # bip_days / bip_obs are day counts (features.py); the cap needs min_days_for_trend observed days.
  if (o.get("bip_obs") or 0) >= MIN_DAYS_FOR_TREND and o.get("bip_days") == o.get("bip_obs"):
    caps.append(f"BIP errors on every observed day, so the score is capped at {BIP_EVERY_DAY_MAX}")
  notes = []
  if o.get("s_error") is None and o.get("vendor") in NO_BIP_VENDORS:
    notes.append(f"{o['vendor']} ONUs report no BIP counters; the error weight was redistributed to the other sub-scores.")
  hw_bad = [f"{n} median {o.get(f'{n}_med')} out of range on {o[f'hw_{n}_days']} day(s)"
            for n in ("tx", "voltage", "temp", "current") if (o.get(f"hw_{n}_days") or 0) > 0]
  if hw_bad:
    notes.append("hardware readings: " + "; ".join(hw_bad))
  for f, txt in (
    ("hw_flag", "ONU hardware readings (Tx/voltage/temp/current) out of range on most days: may be the ONU, not the fiber"),
    ("dq_no_odn", "no ODN inventory row, so expected Rx is less reliable"),
    ("dq_topo_mismatch", "ODN topology does not match the device/PON"),
    ("dq_l2_multi_device", "the L2 name appears on several OLTs"),
    ("range_mismatch", "ranging distance disagrees with the inventory path length"),
  ):
    if o.get(f):
      notes.append(f"{f}: {txt}")
  return {"sub_scores": subs, "weighted_0_1": round(weighted, 3) if weighted is not None else None,
          "caps_applied": caps, "notes": notes}


@_run_errors
async def get_onu_fiber_score(a: OnuScoreIn) -> dict:
  did = await _device_id(a)
  ponport, ontid = a.ponport.strip(), a.ontid.strip()
  d = await fiber.onu_detail(a.date, did, ponport, ontid)
  if d is None:
    name = await fiber.device_name(did)
    raise FiberError(f"no fiber score for device {did} PON {ponport} ONT {ontid}. "
                     + await fiber.unscored_reason(a.date, name or "", ponport, ontid))
  o = d["onu"]
  return {
    "date": d["date"], "window": d["window"], "device_id": did, "onu": o, "explanation": explain(o),
    "model_mae_db": d["model_mae_db"],
    "excess_loss_note": f"expected_rx is a model estimate with about ±{d['model_mae_db']} dB error; "
                        "excess_loss inside that band is noise.",
    "history": d["history"][-14:],
  }
