"""
Load real FTTx telemetry from PostgreSQL and write parquet files that
models.py and app.py can read directly.

For large datasets the telemetry query is streamed through a server-side
cursor in chunks so RAM usage stays bounded regardless of result size.

Sources
-------
onu_pon_1d   -- per-ONU daily optical + traffic metrics
olt_pon_1d   -- per-PON-port daily OLT SFP metrics (joined on device+tstamp+ponport)
odn_onu      -- static ONU topology

Output (written to out_dir/)
------
telemetry.parquet   -- time-series rows, one per ONU per day
topology.parquet    -- one row per ONU (latest snapshot)

.env keys
---------
PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD  (or DATABASE_URL)
EXTRACT_START   ISO date, default 2026-01-01
EXTRACT_END     ISO date, default 2026-06-01
SITE_PREFIX     sitename prefix filter, e.g. "BKK" (empty = all sites)
CHUNK_SIZE      rows per fetch, default 100000
"""

from __future__ import annotations

import os
import sys

from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
import pyarrow as pa
import pyarrow.parquet as pq
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 100_000))

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _conn():
    url = os.getenv("DATABASE_URL")
    if url:
        return psycopg2.connect(url, connect_timeout=30)
    return psycopg2.connect(
        host=os.environ["PG_HOST"],
        port=int(os.getenv("PG_PORT", 5432)),
        dbname=os.environ["PG_DB"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
        connect_timeout=30,
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

TELEMETRY_SQL = """
SELECT
    o.tstamp                        AS timestamp,
    o.device                        AS olt_name,
    o.vendor,
    o.model,
    o.sitename,
    o.ponport,
    o.moduleclass,
    o.l1name                        AS l1_splitter,
    o.l2name                        AS l2_splitter,
    o.ontid,
    o.onu_serial                    AS device_serial,
    o.accessid                      AS circuit_id,
    o.ranging,
    o.pon_rxpwr,
    o.onu_txpwr                     AS onu_tx_power,
    o.onu_rxpwr                     AS onu_rx_power,
    o.onu_current                   AS onu_bias_current,
    o.onu_voltage,
    o.onu_in_biperr,
    o.onu_out_biperr,
    o.onu_in_octets,
    o.onu_out_octets,
    p.pon_txpwr1490                 AS pon_txpwr,
    p.pon_temp,
    p.pon_current1490               AS olt_bias_current,
    p.pon_voltage                   AS olt_voltage,
    p.onu_in_biperr                 AS olt_biperr,
    p.in_pkt                        AS olt_in_octets,
    p.out_pkt                       AS olt_out_octets
FROM onu_pon_1d o
LEFT JOIN olt_pon_1d p
       ON o.device   = p.device
      AND o.tstamp   = p.tstamp
      AND o.ponport  = p.ponport
WHERE o.tstamp BETWEEN %(start)s AND %(end)s
  AND o.device LIKE %(site_prefix)s
ORDER BY o.tstamp, o.device, o.ponport, o.ontid
"""

TOPOLOGY_SQL = """
SELECT
    n.device                        AS olt_name,
    n.ponport,
    n.ontid,
    n.l1name                        AS l1_splitter,
    n.l2name                        AS l2_splitter,
    n.accessid                      AS circuit_id,
    n.ranging,
    n.dropwire,
    n.devicesn                      AS device_serial,
    n.vendor,
    n.model,
    n.moduleclass,
    n.splitratio,
    (COALESCE(n.l1len, 0) + COALESCE(n.l2len, 0) + COALESCE(n.dropwire, 0)) * 1000
                                    AS distance_m
FROM odn_onu n
WHERE n.device LIKE %(site_prefix)s
ORDER BY n.device, n.ponport, n.ontid
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cursor_chunks(conn, sql: str, params: dict, chunk: int):
    """Stream query results via a server-side cursor, yielding DataFrames."""
    with conn.cursor("stream") as cur:
        cur.itersize = chunk
        cur.execute(sql, params)
        while True:
            rows = cur.fetchmany(chunk)
            if not rows:
                break
            cols = [d[0] for d in cur.description]
            yield pd.DataFrame(rows, columns=cols)


def _write_parquet_chunks(conn, sql: str, params: dict, path: str, chunk: int) -> int:
    """Stream query -> parquet file. Returns total row count."""
    writer = None
    schema = None
    total = 0
    for df in _cursor_chunks(conn, sql, params, chunk):
        df["onu_uid"] = (
            df["olt_name"].astype(str) + "-" +
            df["ponport"].astype(str)  + "-" +
            df["ontid"].astype(str)
        )
        # decimal128 precision varies per chunk — normalise to float64
        for col in ["onu_in_biperr", "onu_out_biperr", "onu_in_octets", "onu_out_octets"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

        if schema is None:
            table = pa.Table.from_pandas(df, preserve_index=False)
            schema = table.schema
            writer = pq.ParquetWriter(path, schema, compression="snappy")
        else:
            table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
        writer.write_table(table)
        total += len(df)
        print(f"  ... {total:,} rows written", end="\r")
    if writer:
        writer.close()
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load(out_dir: str = ".") -> None:
    os.makedirs(out_dir, exist_ok=True)

    start       = os.getenv("EXTRACT_START", "2026-01-01")
    end         = os.getenv("EXTRACT_END",   "2026-06-01")
    site_prefix = os.getenv("SITE_PREFIX",   "") + "%"

    params = {"start": start, "end": end, "site_prefix": site_prefix}

    prefix_label = site_prefix.rstrip("%") or "ALL"
    print(f"Connecting to {os.getenv('PG_HOST', 'db')} / {os.getenv('PG_DB', 'db')} ...")
    print(f"  site filter : {prefix_label}*  |  {start} -> {end}  |  chunk={CHUNK_SIZE:,}")
    conn = _conn()

    # -- topology (small enough to load at once) -----------------------------
    print("Loading topology from odn_onu ...")
    topo = pd.read_sql(TOPOLOGY_SQL, conn, params=params)
    topo["onu_uid"] = (
        topo["olt_name"] + "-" + topo["ponport"] + "-" + topo["ontid"].astype(str)
    )
    print(f"  {len(topo):,} ONUs | "
          f"{topo['olt_name'].nunique()} OLTs | "
          f"{topo['ponport'].nunique()} PON ports | "
          f"{topo['l2_splitter'].nunique()} L2 splitters")

    topo_path = os.path.join(out_dir, "topology.parquet")
    topo.to_parquet(topo_path, index=False)
    print(f"  Wrote {topo_path}")

    # -- telemetry (streamed in chunks) --------------------------------------
    telem_path = os.path.join(out_dir, "telemetry.parquet")
    print(f"Loading telemetry {start} -> {end} (streaming {CHUNK_SIZE:,} rows/chunk) ...")
    total = _write_parquet_chunks(conn, TELEMETRY_SQL, params, telem_path, CHUNK_SIZE)
    print()  # clear \r line

    conn.close()

    size_mb = os.path.getsize(telem_path) / 1024**2
    print(f"  Wrote {telem_path}  ({total:,} rows, {size_mb:.0f} MB)")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "data"
    load(out)
