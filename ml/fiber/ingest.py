"""Stage 0: raw JSONL -> typed Parquet under lake/<table>/date=YYYY-MM-DD/."""

import datetime as dt

from common import DATA, LAKE, log, part, sql_path, write_parquet, ymd

_V, _D = "VARCHAR", "DOUBLE"

SCHEMAS = {
  "onu_pon_1d": {
    "tstamp": "DATE", "device": _V, "ponport": _V, "ontid": _V, "vendor": _V, "model": _V,
    "moduleclass": _V, "l1name": _V, "l2name": _V, "ranging": _D,
    "onu_rxpwr": _D, "onu_txpwr": _D, "onu_current": _D, "onu_voltage": _D, "onu_temp": _D,
    "onu_in_biperr": _D, "onu_out_biperr": _D,
    "radius_porterror": _D, "radius_adminreset": _D, "radius_nasrequest": _D, "radius_idletimeout": _D,
    "radius_lostcarrier": _D, "radius_sesstimeout": _D, "radius_userrequest": _D,
  },
  "odn_onu": {
    "device": _V, "ponport": _V, "ontid": _V, "l1name": _V, "l2name": _V,
    "l1len": _D, "l2len": _D, "l1ratio": _D, "l2ratio": _D, "splitratio": _D,
  },
}


def raw_path(table, d):
  return DATA / f"{table}_{ymd(d)}.jsonl"


def ingest_undated_odn(con, force=False):
  """export_jsonl.py writes inventory as an undated data/odn_onu.jsonl (overwritten each export).
  File it into the lake under the date it was exported (its modification date). Returns that date, or None."""
  src = DATA / "odn_onu.jsonl"
  if not src.exists():
    return None
  d = dt.date.fromtimestamp(src.stat().st_mtime)
  dst = part("odn_onu", d)
  if force or not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
    cols = "{" + ", ".join(f"'{k}': '{v}'" for k, v in SCHEMAS["odn_onu"].items()) + "}"
    log(f"ingest {src.name} as snapshot {d}")
    write_parquet(
      con, f"select * from read_json({sql_path(src)}, format = 'newline_delimited', columns = {cols})", dst,
    )
    stale = part("clean_odn", d)
    if stale.exists():
      stale.unlink()
  return d


def lake_dates(table):
  """Dates that have a parquet partition for table."""
  root = LAKE / table
  if not root.exists():
    return []
  return sorted(dt.date.fromisoformat(p.name[5:]) for p in root.glob("date=*") if (p / "part.parquet").exists())


def ingest(con, table, d, force=False):
  """Convert one day's JSONL to Parquet. Returns the parquet path, or None if there is no raw file."""
  dst = part(table, d)
  if dst.exists() and not force:
    return dst
  src = raw_path(table, d)
  if not src.exists():
    return None
  cols = "{" + ", ".join(f"'{k}': '{v}'" for k, v in SCHEMAS[table].items()) + "}"
  log(f"ingest {src.name}")
  return write_parquet(
    con,
    f"select * from read_json({sql_path(src)}, format = 'newline_delimited', columns = {cols})",
    dst,
  )
