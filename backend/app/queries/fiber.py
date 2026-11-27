"""Fiber-score results from the ml/fiber batch pipeline (files, not Postgres).

Reads ml/out (score Parquet, suspect CSVs, DQ JSON) and ml/lake/clean_onu (daily history) with DuckDB.
File paths come only from run dates discovered on disk; every user value is a bound parameter.
Device names in the ML output match device.name in Postgres, which supplies device_id/region/province.
"""
import asyncio
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from app import db
from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
RUN_RE = re.compile(r"^dq_report_(\d{8})\.json$")
LEVELS = ("device", "l1", "l2")
BAD_SCORE = 4
MAX_TREE_NODES = 5000
MAX_PAGE = 500


def _dir(p: str) -> Path:
  path = Path(p)
  return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def out_dir() -> Path:
  return _dir(get_settings().ml_out_dir)


def lake_dir() -> Path:
  return _dir(get_settings().ml_lake_dir)


def _clean(v: Any) -> Any:
  if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
    return None
  if hasattr(v, "isoformat"):
    return v.isoformat()
  return v


def _sql_path(p: Path) -> str:
  return str(p).replace("\\", "/").replace("'", "''")


# ---------------------------------------------------------------- DuckDB

_con: duckdb.DuckDBPyConnection | None = None


def _conn() -> duckdb.DuckDBPyConnection:
  global _con
  if _con is None:
    _con = duckdb.connect(":memory:", config={"threads": get_settings().ml_duckdb_threads})
  return _con


def _query_sync(sql: str, params: list[Any]) -> list[dict[str, Any]]:
  cur = _conn().cursor()  # one cursor per call: cursors are safe to use from separate threads
  try:
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [{c: _clean(v) for c, v in zip(cols, row)} for row in cur.fetchall()]
  finally:
    cur.close()


async def _query(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
  return await asyncio.to_thread(_query_sync, sql, params or [])


# ---------------------------------------------------------------- runs

@dataclass(frozen=True)
class Run:
  date: str  # YYYYMMDD
  report: Path
  scores: Path

  @property
  def iso(self) -> str:
    return f"{self.date[:4]}-{self.date[4:6]}-{self.date[6:]}"

  def suspects(self, level: str) -> Path:
    return self.report.parent / f"suspect_{level}_{self.date}.parquet"


def list_runs() -> list[Run]:
  d = out_dir()
  if not d.is_dir():
    return []
  runs = []
  for f in d.iterdir():
    m = RUN_RE.match(f.name)
    if m and (d / f"onu_fiber_score_{m[1]}.parquet").is_file():
      runs.append(Run(m[1], f, d / f"onu_fiber_score_{m[1]}.parquet"))
  return sorted(runs, key=lambda r: r.date, reverse=True)


class RunNotFound(LookupError):
  pass


def get_run(date: str | None) -> Run:
  runs = list_runs()
  if not runs:
    raise RunNotFound("no fiber-score runs found in " + str(out_dir()))
  if not date:
    return runs[0]
  key = date.replace("-", "")
  for r in runs:
    if r.date == key:
      return r
  raise RunNotFound(f"no fiber-score run for {date}")


_file_cache: dict[tuple[str, float], Any] = {}


def _cached(path: Path, loader: Any) -> Any:
  key = (str(path), path.stat().st_mtime)
  if key not in _file_cache:
    _file_cache[key] = loader(path)
  return _file_cache[key]


def _report(run: Run) -> dict[str, Any]:
  return _cached(run.report, lambda p: json.loads(p.read_text(encoding="utf-8")))


def runs_payload() -> list[dict[str, Any]]:
  out = []
  for r in list_runs():
    rep = _report(r)
    out.append({
      "date": r.iso, "window": rep.get("window"), "days": len(rep.get("days", [])),
      "mean_conf": rep.get("mean_conf"), "bad_onus": rep.get("attribution", {}).get("bad_onus"),
    })
  return out


def summary(date: str | None) -> dict[str, Any]:
  run = get_run(date)
  rep = _report(run)
  att = rep.get("attribution", {})
  model = rep.get("model", {})
  runs = list_runs()
  idx = [r.date for r in runs].index(run.date)
  prev = None
  if idx + 1 < len(runs):
    p = _report(runs[idx + 1])
    pa = p.get("attribution", {})
    prev = {"date": runs[idx + 1].iso, "window": p.get("window"), "days": len(p.get("days", [])),
            "bad_onus": pa.get("bad_onus"), "onus": p.get("onus"), "suspects": pa.get("suspects", {})}
  return {
    "date": run.iso,
    "window": rep.get("window"),
    "days": rep.get("days", []),
    "odn_date": rep.get("odn_date"),
    "onus": rep.get("onus"),
    "unscored_onus": rep.get("unscored_onus"),
    "mean_conf": rep.get("mean_conf"),
    "histogram": {int(k): v for k, v in rep.get("score_histogram", {}).items()},
    "bad_threshold": BAD_SCORE,
    "bad_onus": att.get("bad_onus"),
    "global_bad_rate": att.get("global_bad_rate"),
    "attributed": att.get("attributed", {}),
    "suspects": att.get("suspects", {}),
    "model": {k: model.get(k) for k in (
      "model_date", "holdout_mae_db", "trained_mae_db", "baseline_mae_db", "mae_drift_db", "feature_importance_gain",
      "train_onus", "holdout_onus")},
    "inventory": rep.get("join", {}),
    "by_vendor": {v: {"rows": s.get("rows")} for v, s in rep.get("by_vendor", {}).items()},
    "prev": prev,
  }


# ---------------------------------------------------------------- suspects

def _load_suspects(path: Path) -> list[dict[str, Any]]:
  return _query_sync(f"SELECT * FROM read_parquet('{_sql_path(path)}')", [])


_enriched: dict[tuple[str, str, float], list[dict[str, Any]]] = {}


async def _device_info(names: list[str]) -> dict[str, dict[str, Any]]:
  if not names:
    return {}
  rows = await db.fetch(
    """SELECT DISTINCT ON (d.name) d.id, d.name, d.vendor, d.model, d.region, d.province, d.sitename
    FROM device d WHERE d.name = ANY($1::text[]) ORDER BY d.name, d.lastseen DESC NULLS LAST""",
    names,
  )
  return {r["name"]: dict(r) for r in rows}


async def suspects_all(run: Run, level: str) -> list[dict[str, Any]]:
  """All suspect rows of one level, enriched with device id/region/province (cached per file version)."""
  path = run.suspects(level)
  if not path.is_file():
    return []
  key = (str(path), level, path.stat().st_mtime)
  if key not in _enriched:
    rows = _cached(path, _load_suspects)
    info = await _device_info(sorted({r["device"] for r in rows if r.get("device")}))
    out = []
    for r in rows:
      d = info.get(r.get("device") or "", {})
      out.append({
        **r,
        "device_id": d.get("id"), "region": d.get("region"), "province": d.get("province"), "sitename": d.get("sitename"),
        "vendor": r.get("vendor") or d.get("vendor"), "model": r.get("model") or d.get("model"),
      })
    if len(_enriched) > 30:
      _enriched.clear()
    _enriched[key] = out
  return _enriched[key]


SUSPECT_FILTERS = ("region", "province", "vendor")


def _facets(rows: list[dict[str, Any]], active: dict[str, str | None]) -> dict[str, list[dict[str, Any]]]:
  out: dict[str, list[dict[str, Any]]] = {}
  for f in SUSPECT_FILTERS:
    counts: dict[str, int] = {}
    for r in rows:
      if all(not v or r.get(k) == v for k, v in active.items() if k != f):
        val = r.get(f)
        if val:
          counts[val] = counts.get(val, 0) + 1
    out[f] = [{"value": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
  return out


async def suspects(
  date: str | None, level: str, region: str | None, province: str | None, vendor: str | None, q: str | None,
  sort: str, order: str, page: int, size: int,
) -> dict[str, Any]:
  run = get_run(date)
  rows = await suspects_all(run, level)
  active = {"region": region, "province": province, "vendor": vendor}
  facets = _facets(rows, active)
  needle = (q or "").strip().lower()
  sel = [
    r for r in rows
    if all(not v or r.get(k) == v for k, v in active.items())
    and (not needle or any(needle in str(r.get(c) or "").lower() for c in ("device", "l1name", "l2name", "sitename")))
  ]
  if sel and sort not in sel[0]:
    sort = "impact"
  present = [r for r in sel if r.get(sort) is not None]
  present.sort(key=lambda r: r[sort], reverse=order == "desc")
  sel = present + [r for r in sel if r.get(sort) is None]
  start = (page - 1) * size
  return {"date": run.iso, "level": level, "items": sel[start:start + size], "page": page, "size": size,
          "total": len(sel), "facets": facets}


async def suspect_keys(run: Run) -> dict[str, set[str]]:
  out = {}
  for level, col in (("device", "device"), ("l1", "l1name"), ("l2", "l2name")):
    p = run.suspects(level)
    out[level] = {r[col] for r in _cached(p, _load_suspects)} if p.is_file() else set()
  return out


# ---------------------------------------------------------------- per-OLT

async def device_name(device_id: int) -> str | None:
  return await db.fetchval("SELECT name FROM device WHERE id = $1", device_id)


ATT_COLS = (("l2", "att_l2"), ("l1", "att_l1"), ("device", "att_device"), ("drop", "att_drop"), ("onu_hw", "att_hw"))
PORT_ORDER = "list_transform(string_split(ponport, '-'), lambda x: try_cast(x AS BIGINT))"


async def device_tree(date: str | None, device_id: int) -> dict[str, Any] | None:
  name = await device_name(device_id)
  if name is None:
    return None
  run = get_run(date)
  rows = await _query(
    f"""SELECT ponport, l1name, l2name, count(*) AS n_onu, count(*) FILTER (WHERE bad) AS n_bad,
      min(score) AS min_score, round(median(rx_med), 2) AS med_rx, round(median(excess_loss), 2) AS med_excess_loss,
      round(median(peer_delta_l2), 2) AS med_peer_delta,
      count(*) FILTER (WHERE attributed_to = 'l2') AS att_l2, count(*) FILTER (WHERE attributed_to = 'l1') AS att_l1,
      count(*) FILTER (WHERE attributed_to = 'device') AS att_device, count(*) FILTER (WHERE attributed_to = 'drop') AS att_drop,
      count(*) FILTER (WHERE attributed_to = 'onu_hw') AS att_hw
    FROM read_parquet('{_sql_path(run.scores)}') WHERE device = ?
    GROUP BY ponport, l1name, l2name ORDER BY {PORT_ORDER}, ponport, l2name LIMIT {MAX_TREE_NODES}""",
    [name],
  )
  keys = await suspect_keys(run)
  ports: dict[tuple[str, str | None], dict[str, Any]] = {}
  for r in rows:
    k = (r["ponport"], r["l1name"])
    p = ports.get(k)
    if p is None:
      p = ports[k] = {"ponport": r["ponport"], "l1name": r["l1name"], "n_onu": 0, "n_bad": 0, "min_score": None,
                      "suspect": r["l1name"] in keys["l1"] if r["l1name"] else False, "l2": []}
    p["n_onu"] += r["n_onu"]
    p["n_bad"] += r["n_bad"]
    if r["min_score"] is not None:
      p["min_score"] = r["min_score"] if p["min_score"] is None else min(p["min_score"], r["min_score"])
    p["l2"].append({
      "l2name": r["l2name"], "n_onu": r["n_onu"], "n_bad": r["n_bad"], "min_score": r["min_score"],
      "med_rx": r["med_rx"], "med_excess_loss": r["med_excess_loss"], "med_peer_delta": r["med_peer_delta"],
      "suspect": r["l2name"] in keys["l2"] if r["l2name"] else False,
      "attributed": {a: r[c] for a, c in ATT_COLS if r[c]},
    })
  # Port-level medians need ONU-level data; a second small aggregate keeps them exact.
  port_stats = await _query(
    f"""SELECT ponport, l1name, round(median(rx_med), 2) AS med_rx, round(median(excess_loss), 2) AS med_excess_loss
    FROM read_parquet('{_sql_path(run.scores)}') WHERE device = ? GROUP BY ALL""",
    [name],
  )
  ps = {(r["ponport"], r["l1name"]): r for r in port_stats}
  items = []
  for k, p in ports.items():
    s = ps.get(k, {})
    p["med_rx"], p["med_excess_loss"] = s.get("med_rx"), s.get("med_excess_loss")
    p["l2"].sort(key=lambda x: (-x["n_bad"], x["l2name"] or ""))
    items.append(p)
  n_onu = sum(p["n_onu"] for p in items)
  n_bad = sum(p["n_bad"] for p in items)
  return {
    "date": run.iso, "device": name, "device_id": device_id, "device_suspect": name in keys["device"],
    "n_onu": n_onu, "n_bad": n_bad, "n_ports": len(items),
    "n_suspect_l1": sum(p["suspect"] for p in items), "n_suspect_l2": sum(x["suspect"] for p in items for x in p["l2"]),
    "items": items, "truncated": len(rows) >= MAX_TREE_NODES,
  }


ONU_COLS = """ponport, ontid, l1name, l2name, vendor, score, conf, rx_med, expected_rx, excess_loss, peer_delta_l2,
  peer_delta_l1, bip_days, days_obs, hw_flag, bad, attributed_to"""
HW_READINGS = ("tx", "voltage", "temp", "current")
HW_COLS = ("hw_days", *(f"{n}_med" for n in HW_READINGS), *(f"hw_{n}_days" for n in HW_READINGS))
_schema_cache: dict[tuple[str, float], set[str]] = {}


def _onu_cols(run: Run) -> str:
  """ONU_COLS plus the hardware-reading columns when this run's Parquet has them (runs before 2026-11-25 do not)."""
  key = (str(run.scores), run.scores.stat().st_mtime)
  if key not in _schema_cache:
    rows = _query_sync(f"DESCRIBE SELECT * FROM read_parquet('{_sql_path(run.scores)}')", [])
    _schema_cache[key] = {r["column_name"] for r in rows}
  have = _schema_cache[key]
  extra = [c for c in HW_COLS if c in have]
  return ONU_COLS + ("".join(f", {c}" for c in extra))


ONU_SORT = {
  "score": "score", "rx_med": "rx_med", "excess_loss": "excess_loss", "peer_delta_l2": "peer_delta_l2",
  "bip_days": "bip_days", "conf": "conf", "ontid": "try_cast(ontid AS BIGINT)", "ponport": PORT_ORDER, "l2name": "l2name",
}


async def device_onus(
  date: str | None, device_id: int, ponport: str | None, l1name: str | None, l2name: str | None,
  max_score: int | None, sort: str, order: str, page: int, size: int,
) -> dict[str, Any] | None:
  name = await device_name(device_id)
  if name is None:
    return None
  run = get_run(date)
  where, params = ["device = ?"], [name]
  for col, v in (("ponport", ponport), ("l1name", l1name), ("l2name", l2name)):
    if v:
      where.append(f"{col} = ?")
      params.append(v)
  if max_score is not None:
    where.append("score <= ?")
    params.append(max_score)
  w = " AND ".join(where)
  src = f"read_parquet('{_sql_path(run.scores)}')"
  direction = "DESC" if order == "desc" else "ASC"
  ob = ONU_SORT.get(sort, "score")
  rows = await _query(
    f"""SELECT {_onu_cols(run)}, count(*) OVER () AS _total FROM {src} WHERE {w}
    ORDER BY {ob} {direction} NULLS LAST, {PORT_ORDER}, try_cast(ontid AS BIGINT) LIMIT ? OFFSET ?""",
    [*params, size, (page - 1) * size],
  )
  total = rows[0].pop("_total") if rows else 0
  for r in rows[1:]:
    r.pop("_total")
  return {"date": run.iso, "items": rows, "page": page, "size": size, "total": total}


ATTRIBUTIONS = ("drop", "l2", "l1", "device", "onu_hw")


async def bad_onus(
  date: str | None, attributed_to: str, q: str | None, sort: str, order: str, page: int, size: int,
) -> dict[str, Any]:
  """Bad ONUs across all OLTs with one attribution (network-wide list), enriched with device id/province."""
  run = get_run(date)
  where, params = ["bad", "attributed_to = ?"], [attributed_to]
  needle = (q or "").strip()
  if needle:
    where.append("(device ILIKE ? OR l1name ILIKE ? OR l2name ILIKE ?)")
    params += [f"%{needle}%"] * 3
  direction = "DESC" if order == "desc" else "ASC"
  ob = "device" if sort == "device" else ONU_SORT.get(sort, "score")
  rows = await _query(
    f"""SELECT device, {_onu_cols(run)}, count(*) OVER () AS _total FROM read_parquet('{_sql_path(run.scores)}')
    WHERE {' AND '.join(where)}
    ORDER BY {ob} {direction} NULLS LAST, device, {PORT_ORDER}, try_cast(ontid AS BIGINT) LIMIT ? OFFSET ?""",
    [*params, size, (page - 1) * size],
  )
  total = rows[0]["_total"] if rows else 0
  info = await _device_info(sorted({r["device"] for r in rows if r.get("device")}))
  for r in rows:
    r.pop("_total")
    d = info.get(r["device"], {})
    r["device_id"], r["province"], r["region"] = d.get("id"), d.get("province"), d.get("region")
  return {"date": run.iso, "attributed_to": attributed_to, "items": rows, "page": page, "size": size, "total": total}


async def ponport_scores(date: str | None, device_id: int) -> dict[str, Any] | None:
  name = await device_name(device_id)
  if name is None:
    return None
  run = get_run(date)
  rows = await _query(
    f"""SELECT ponport, count(*) AS n_onu, count(*) FILTER (WHERE bad) AS n_bad, min(score) AS min_score
    FROM read_parquet('{_sql_path(run.scores)}') WHERE device = ? GROUP BY ponport""",
    [name],
  )
  return {"date": run.iso, "items": {r.pop("ponport"): r for r in rows}}


async def unscored_reason(date: str | None, device_name: str, ponport: str, ontid: str) -> str:
  """Why an ONU has no row in a run. Every ONU with readings in the window is scored, so a missing ONU
  is either not in the ODN inventory (wrong port/ONT id) or had no optical readings in the window."""
  run = get_run(date)
  days = _report(run).get("days") or []
  window = f"{days[0]}..{days[-1]}" if days else f"the run window ending {run.iso}"
  inv = await db.fetchrow(
    "SELECT accessid FROM odn_onu WHERE device = $1 AND ponport = $2 AND ontid = $3", device_name, ponport, ontid,
  )
  if inv is None:
    on_port = await db.fetchval("SELECT count(*) FROM odn_onu WHERE device = $1 AND ponport = $2", device_name, ponport)
    where = f"PON {ponport} has {on_port} ONUs in the inventory" if on_port else f"{device_name} has no PON port {ponport} in the inventory"
    return f"ONT {ontid} on {device_name} PON {ponport} is not in the ODN inventory (odn_onu); {where}. Check the PON port and ONT id."
  return (
    f"Not scored in run {run.iso}: the ONU is in the inventory (access id {inv['accessid']}) but had no optical "
    f"readings in {window}. Usually the ONU is offline or the service is inactive; only ONUs with Rx readings get a score."
  )


ONU_BRIEF_COLS = (
  "score", "round(conf, 3) AS conf", "bad", "attributed_to", "round(rx_med, 2) AS rx_med",
  "round(expected_rx, 2) AS expected_rx", "round(excess_loss, 2) AS excess_loss",
  "round(peer_delta_l2, 2) AS peer_delta_l2", "hw_flag",
)


async def onu_brief(device_name: str, ponport: str, ontid: str) -> dict[str, Any] | None:
  """Headline fiber score of one ONU in the latest run (by OLT name, as stored in the ML output)."""
  run = get_run(None)
  rows = await _query(
    f"""SELECT {', '.join(ONU_BRIEF_COLS)} FROM read_parquet('{_sql_path(run.scores)}')
    WHERE device = ? AND ponport = ? AND ontid = ? LIMIT 1""",
    [device_name, ponport, ontid],
  )
  return {"date": run.iso, **rows[0]} if rows else None


async def onu_detail(date: str | None, device_id: int, ponport: str, ontid: str) -> dict[str, Any] | None:
  name = await device_name(device_id)
  if name is None:
    return None
  run = get_run(date)
  rows = await _query(
    f"SELECT * FROM read_parquet('{_sql_path(run.scores)}') WHERE device = ? AND ponport = ? AND ontid = ? LIMIT 1",
    [name, ponport, ontid],
  )
  if not rows:
    return None
  onu = rows[0]
  history: list[dict[str, Any]] = []
  lake = lake_dir() / "clean_onu"
  if lake.is_dir() and any(lake.glob("date=*/*.parquet")):
    history = await _query(
      f"""SELECT date, round(rx, 2) AS rx, bip_in, lostcarrier, hw_flag
      FROM read_parquet('{_sql_path(lake)}/date=*/*.parquet', hive_partitioning = true)
      WHERE device = ? AND ponport = ? AND ontid = ? AND date <= ?::DATE ORDER BY date DESC LIMIT 30""",
      [name, ponport, ontid, run.iso],
    )
    history.reverse()
  rep = _report(run)
  return {
    "date": run.iso, "device_id": device_id, "onu": onu, "history": history,
    "model_mae_db": rep.get("model", {}).get("holdout_mae_db"), "window": rep.get("window"),
  }
