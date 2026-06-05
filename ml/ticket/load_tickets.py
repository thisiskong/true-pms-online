"""
Load customer tickets from PostgreSQL and write to local JSON.

Usage:
  uv run python load_tickets.py

Reads config from .env:
  PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD
  TABLE_TICKETS   -- table name (default: ticket)
  EXTRACT_START   -- ISO date
  EXTRACT_END     -- ISO date
  OUTPUT_FILE     -- output filename (default: tickets.json)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

CHUNK_SIZE = 10_000


def _conn():
  return psycopg2.connect(
    host=os.environ["PG_HOST"],
    port=int(os.getenv("PG_PORT", 5432)),
    dbname=os.environ["PG_DB"],
    user=os.environ["PG_USER"],
    password=os.environ["PG_PASSWORD"],
    connect_timeout=30,
  )


def _serialize(obj):
  if isinstance(obj, (date, datetime)):
    return obj.isoformat()
  return str(obj)


def load(output_file: str | None = None) -> None:
  table  = os.getenv("TABLE_TICKETS", "ticket")
  start  = os.getenv("EXTRACT_START", "2024-01-01")
  end    = os.getenv("EXTRACT_END",   "2026-06-01")
  output = output_file or os.getenv("OUTPUT_FILE", "tickets.jsonl")
  out_path = Path(__file__).parent / output

  print(f"Connecting to {os.getenv('PG_HOST')} / {os.getenv('PG_DB')} ...")
  print(f"  table  : {table}")
  print(f"  range  : {start} -> {end}")

  conn = _conn()

  # row count first
  with conn.cursor() as cur:
    cur.execute(
      f"SELECT COUNT(*) FROM {table} WHERE tstamp BETWEEN %s AND %s",
      (start, end),
    )
    total = cur.fetchone()[0]
  print(f"  rows   : {total:,}")

  sql = f"""
    SELECT
      ticketid, tstamp, createtime, completetime,
      accessid, faulttype, faultcause, subcategory,
      faultstatus, networkdisp, device, l1name, l2name
    FROM {table}
    WHERE tstamp BETWEEN %(start)s AND %(end)s
    ORDER BY tstamp, ticketid
  """

  records = []
  fetched = 0

  with conn.cursor("ticket_stream", cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.itersize = CHUNK_SIZE
    cur.execute(sql, {"start": start, "end": end})
    while True:
      rows = cur.fetchmany(CHUNK_SIZE)
      if not rows:
        break
      records.extend(dict(r) for r in rows)
      fetched += len(rows)
      print(f"  ... {fetched:,} / {total:,} rows fetched", end="\r")

  conn.close()
  print()

  print(f"Writing {len(records):,} records to {out_path} ...")
  with open(out_path, "w", encoding="utf-8") as f:
    for record in records:
      f.write(json.dumps(record, ensure_ascii=False, default=_serialize) + "\n")

  size_mb = out_path.stat().st_size / 1024**2

  # summary stats
  fault_types = {r["faulttype"] for r in records if r.get("faulttype")}
  statuses    = {r["faultstatus"] for r in records if r.get("faultstatus")}

  print(f"Done.")
  print(f"  output         : {out_path}  ({size_mb:.1f} MB)")
  print(f"  total records  : {len(records):,}")
  print(f"  distinct faulttype  : {len(fault_types)}")
  print(f"  distinct status     : {statuses}")


if __name__ == "__main__":
  out = sys.argv[1] if len(sys.argv) > 1 else None
  load(out)
