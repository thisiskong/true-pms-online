# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg[binary]>=3.1"]
# ///
"""Export ONU daily metrics and ODN inventory from Postgres to JSONL.

Usage (credentials are read from ml/.env, or from the environment):
  uv run export_jsonl.py onu_pon_1d                    # daily metrics for yesterday -> data/onu_pon_1d_YYYYMMDD.jsonl
  uv run export_jsonl.py onu_pon_1d --date 2026-11-20  # daily metrics for one specific day
  uv run export_jsonl.py odn_onu                       # current inventory -> data/odn_onu.jsonl
  uv run export_jsonl.py odn_onu --out D:/dump

Connection settings come from the standard libpq env vars
(PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD); defaults match
application.properties except the password, which must be supplied.
"""

import argparse
import datetime as dt
import decimal
import json
import os
import sys
import time
from pathlib import Path

import psycopg

QUERIES = {
  "onu_pon_1d": """
    select tstamp, device, ponport, ontid, vendor, model, moduleclass, l1name, l2name, ranging,
           onu_rxpwr, onu_txpwr, onu_current, onu_voltage, onu_temp,
           onu_in_biperr, onu_out_biperr,
           radius_porterror, radius_adminreset, radius_nasrequest, radius_idletimeout,
           radius_lostcarrier, radius_sesstimeout, radius_userrequest
    from onu_pon_1d
    where tstamp >= %(date)s::date
      and tstamp <  %(date)s::date + 1
  """,
  "odn_onu": """
    select device, ponport, ontid, l1name, l2name, l1len, l2len, l1ratio, l2ratio, splitratio
    from odn_onu
  """,
}


def to_json(value):
  if isinstance(value, decimal.Decimal):
    return float(value)
  if isinstance(value, (dt.datetime, dt.date, dt.time)):
    return value.isoformat()
  if isinstance(value, dt.timedelta):
    return value.total_seconds()
  if isinstance(value, (bytes, memoryview)):
    return bytes(value).hex()
  return str(value)


def load_dotenv(path=Path(__file__).with_name(".env")):
  """Minimal .env loader; real environment variables take precedence."""
  if not path.exists():
    return
  for line in path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    key, value = line.split("=", 1)
    os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def connect():
  load_dotenv()
  if not os.environ.get("PGPASSWORD"):
    sys.exit("PGPASSWORD is not set")
  return psycopg.connect(
    host=os.environ.get("PGHOST", "10.50.238.194"),
    port=int(os.environ.get("PGPORT", "5432")),
    dbname=os.environ.get("PGDATABASE", "pmsonline"),
    user=os.environ.get("PGUSER", "pmsonline"),
    application_name="ml-export-jsonl",
  )


def export(conn, name, sql, params, out_path, batch_size):
  tmp_path = out_path.with_suffix(".jsonl.part")
  started = time.monotonic()
  rows = 0

  # Server-side (named) cursor streams rows instead of loading them all into memory.
  with conn.cursor(name=f"export_{name}") as cur, open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
    cur.itersize = batch_size
    cur.execute(sql, params)
    cols = None
    for row in cur:
      if cols is None:
        cols = [d.name for d in cur.description]
      f.write(json.dumps(dict(zip(cols, row)), default=to_json, ensure_ascii=False))
      f.write("\n")
      rows += 1
      if rows % 500_000 == 0:
        print(f"  {name}: {rows:,} rows ...", flush=True)

  tmp_path.replace(out_path)
  print(f"{name}: {rows:,} rows -> {out_path} ({time.monotonic() - started:.1f}s)")


def main():
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("dataset", choices=list(QUERIES), help="which dataset to export")
  ap.add_argument("--out", default="data", help="output directory (default: ./data)")
  ap.add_argument("--date", type=dt.date.fromisoformat,
                  help="onu_pon_1d only: day to export, YYYY-MM-DD (default: yesterday)")
  ap.add_argument("--batch-size", type=int, default=50_000, help="rows fetched per round trip")
  args = ap.parse_args()

  name, sql = args.dataset, QUERIES[args.dataset]
  dated = "%(date)s" in sql
  if args.date and not dated:
    ap.error(f"--date does not apply to {name}: it is a current snapshot")
  day = args.date or dt.date.today() - dt.timedelta(days=1)

  out_dir = Path(args.out)
  out_dir.mkdir(parents=True, exist_ok=True)
  if dated:
    params, out_path = {"date": day}, out_dir / f"{name}_{day:%Y%m%d}.jsonl"
  else:
    # Inventory is a current snapshot: one undated file, overwritten each export.
    params, out_path = None, out_dir / f"{name}.jsonl"

  with connect() as conn:
    # Read-only session: guards against accidental writes to the production DB.
    conn.read_only = True
    export(conn, name, sql, params, out_path, args.batch_size)


if __name__ == "__main__":
  main()
