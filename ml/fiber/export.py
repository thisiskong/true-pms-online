"""Export straight from Postgres into the Parquet lake (no JSONL), via DuckDB's postgres extension.

Usage (from ml/; credentials from ml/.env or PG* env vars):
  uv run fiber/export.py onu_pon_1d                          # yesterday
  uv run fiber/export.py onu_pon_1d --date 2026-11-20
  uv run fiber/export.py onu_pon_1d --start 2026-11-01 --end 2026-11-20
  uv run fiber/export.py odn_onu                             # current inventory, filed under today's date

Writes lake/onu_pon_1d/date=YYYY-MM-DD/part.parquet and lake/odn_onu/date=YYYY-MM-DD/part.parquet,
the same partitions fiber/run.py reads (so run.py skips its own ingest for them).
The Postgres connection is read-only.

onu_pon_1d is partitioned by day in Postgres (onu_pon_1d_pYYYYMMDD00). The export finds that day's
partition in the catalog and scans it in parallel (--pg-threads connections, default 4): about 4x
faster than a single query. If no partition is found it falls back to one filtered query.
"""

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ROOT, connect, log, part, write_parquet  # noqa: E402

# Only the columns the pipeline uses; numeric columns are cast to double.
ONU_COLUMNS = """
  tstamp::date as tstamp, device, ponport, ontid::varchar as ontid, vendor, model, moduleclass,
  l1name, l2name, ranging::double as ranging,
  onu_rxpwr::double as onu_rxpwr, onu_txpwr::double as onu_txpwr, onu_current::double as onu_current,
  onu_voltage::double as onu_voltage, onu_temp::double as onu_temp,
  onu_in_biperr::double as onu_in_biperr, onu_out_biperr::double as onu_out_biperr,
  radius_lostcarrier::double as radius_lostcarrier
"""

# Fallback queries, run inside Postgres with postgres_query().
QUERIES = {
  "onu_pon_1d": """
    select tstamp::date as tstamp, device, ponport, ontid::varchar as ontid, vendor, model, moduleclass,
           l1name, l2name, ranging::double precision as ranging,
           onu_rxpwr::double precision as onu_rxpwr, onu_txpwr::double precision as onu_txpwr,
           onu_current::double precision as onu_current, onu_voltage::double precision as onu_voltage,
           onu_temp::double precision as onu_temp,
           onu_in_biperr::double precision as onu_in_biperr, onu_out_biperr::double precision as onu_out_biperr,
           radius_lostcarrier::double precision as radius_lostcarrier
    from onu_pon_1d
    where tstamp >= date '{day}' and tstamp < date '{day}' + 1
  """,
  "odn_onu": """
    select device, ponport, ontid::varchar as ontid, l1name, l2name,
           l1len::double precision as l1len, l2len::double precision as l2len,
           l1ratio::double precision as l1ratio, l2ratio::double precision as l2ratio,
           splitratio::double precision as splitratio
    from odn_onu
  """,
}


def load_env(path=ROOT / ".env"):
  """Load ml/.env into the environment; real environment variables win. libpq reads PG* from there."""
  if not path.exists():
    return
  for line in path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
      k, v = line.split("=", 1)
      os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def attach(con):
  load_env()
  if not os.environ.get("PGPASSWORD"):
    raise SystemExit("PGPASSWORD is not set (ml/.env or environment)")
  con.execute("install postgres; load postgres")
  # Empty DSN: libpq takes host/port/db/user/password from the PG* environment variables.
  con.execute("attach '' as pg (type postgres, read_only)")


def day_partition(con, day):
  """Name of the onu_pon_1d partition holding exactly this day, or None."""
  rows = con.execute(f"""
    select * from postgres_query('pg', $q$
      select c.relname from pg_inherits i join pg_class c on c.oid = i.inhrelid
      where i.inhparent = 'onu_pon_1d'::regclass
        and pg_get_expr(c.relpartbound, c.oid) =
            'FOR VALUES FROM (''{day.isoformat()}'') TO (''{(day + dt.timedelta(days=1)).isoformat()}'')'
    $q$)""").fetchall()
  return rows[0][0] if rows else None


def source_sql(con, dataset, day):
  if dataset == "onu_pon_1d":
    name = day_partition(con, day)
    if name:
      return f"select {ONU_COLUMNS} from pg.public.{name}", f"partition {name}"
  sql = QUERIES[dataset].format(day=day.isoformat())   # day is a parsed date, so this is not injectable
  return f"select * from postgres_query('pg', $q${sql}$q$)", "single query"


def export(con, dataset, day, force=False):
  dst = part(dataset, day)
  if dst.exists() and not force:
    log(f"{dataset} {day}: already in lake, skipped (use --force to replace)")
    return dst
  started = time.monotonic()
  sql, how = source_sql(con, dataset, day)
  write_parquet(con, sql, dst)
  if dataset == "odn_onu":
    stale = part("clean_odn", day)   # force run.py to re-cleanse this snapshot
    if stale.exists():
      stale.unlink()
  elif (stale := part("clean_onu", day)).exists():
    stale.unlink()
  rows = con.execute(f"select count(*) from read_parquet('{dst.as_posix()}')").fetchone()[0]
  log(f"{dataset} {day}: {rows:,} rows, {dst.stat().st_size / 1e6:.0f} MB in {time.monotonic() - started:.0f}s ({how})")
  if rows == 0:
    log(f"warning: {dataset} {day} is empty")
  return dst


def main():
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("dataset", choices=list(QUERIES))
  ap.add_argument("--date", type=dt.date.fromisoformat, help="onu_pon_1d: one day (default: yesterday)")
  ap.add_argument("--start", type=dt.date.fromisoformat, help="onu_pon_1d: first day of a range")
  ap.add_argument("--end", type=dt.date.fromisoformat, help="onu_pon_1d: last day of a range (inclusive)")
  ap.add_argument("--force", action="store_true", help="replace partitions that already exist")
  ap.add_argument("--pg-threads", type=int, default=4,
                  help="parallel Postgres connections for the partition scan (default 4; mind the DB load)")
  args = ap.parse_args()

  if args.dataset == "odn_onu":
    if args.date or args.start or args.end:
      ap.error("odn_onu is a current snapshot: it takes no dates (it is filed under today's date)")
    days = [dt.date.today()]
  elif args.start or args.end:
    if not (args.start and args.end) or args.date:
      ap.error("use --start and --end together, without --date")
    if args.end < args.start:
      ap.error("--end is before --start")
    days = [args.start + dt.timedelta(days=i) for i in range((args.end - args.start).days + 1)]
  else:
    days = [args.date or dt.date.today() - dt.timedelta(days=1)]

  con = connect()
  con.execute(f"set threads = {max(1, args.pg_threads)}")
  attach(con)
  for day in days:
    export(con, args.dataset, day, args.force)


if __name__ == "__main__":
  main()
