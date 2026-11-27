"""Shared paths, config and helpers for the fiber score pipeline."""

import datetime as dt
from pathlib import Path

import duckdb
import yaml

ROOT = Path(__file__).resolve().parent.parent   # ml/
LAKE = ROOT / "lake"                             # parquet, partitioned by date
OUT = ROOT / "out"                               # scores, suspect lists, reports
CFG_PATH = Path(__file__).with_name("ranges.yaml")


def load_cfg(path=CFG_PATH):
  with open(path, encoding="utf-8") as f:
    return yaml.safe_load(f)


def ymd(d):
  return f"{d:%Y%m%d}"


def part(table, d):
  return LAKE / table / f"date={d.isoformat()}" / "part.parquet"


def sql_path(p):
  return "'" + Path(p).as_posix().replace("'", "''") + "'"


def connect():
  con = duckdb.connect()
  con.execute("set preserve_insertion_order = false")
  return con


def write_parquet(con, select_sql, dst):
  """Run a SELECT and write it atomically to dst."""
  dst = Path(dst)
  dst.parent.mkdir(parents=True, exist_ok=True)
  tmp = dst.with_suffix(".parquet.part")
  con.execute(f"copy ({select_sql}) to {sql_path(tmp)} (format parquet, compression zstd)")
  tmp.replace(dst)
  return dst


def log(msg):
  print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def lake_dates(table):
  """Dates that have a parquet partition for table."""
  root = LAKE / table
  if not root.exists():
    return []
  return sorted(dt.date.fromisoformat(p.name[5:]) for p in root.glob("date=*") if (p / "part.parquet").exists())
