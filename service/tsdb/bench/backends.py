"""Same dataset, both backends: ingest throughput, storage size, and a query suite (warm median/p95).

Dataset: 250 devices x 40 interfaces x 7 metrics, 5-minute points for 1 day (288 cycles)
= 20.16M points, generated deterministically and streamed through the real ingest pipeline.
Queries go through run_query (the same code path as POST /api/query).
Usage (from service/tsdb, with CH_* and PG_* set): PYTHONPATH=src uv run python bench/backends.py out.json
"""
import asyncio
import hashlib
import json
import math
import os
import statistics
import sys
import time

os.environ["CH_DATABASE"] = os.environ["PG_SCHEMA"] = "tsdb_bench"

from tsdb import ch, config, migrate  # noqa: E402
from tsdb.ingest.pipeline import IngestResult, ingest_stream  # noqa: E402
from tsdb.ingest.series import SeriesCache  # noqa: E402
from tsdb.query.models import QueryIn  # noqa: E402
from tsdb.query.run import run_query  # noqa: E402
from tsdb.store import make_store  # noqa: E402

METRICS = ["in_octets", "out_octets", "in_rate", "out_rate", "in_bw", "out_bw", "in_err"]
N_DEV, N_INTF, N_CYCLES = 250, 40, 288
DAY_START = (int(time.time()) - 2 * 86400) // 86400 * 86400      # a whole UTC day, 2 days ago
START, END = DAY_START, DAY_START + 86400 - 1
REPS = 15


def ip(d: int) -> str:
  return f"10.{d // 200}.{d % 200}.1"


def gen():
  """Yields ~1 MB chunks; one cycle at a time, so memory stays small."""
  for c in range(N_CYCLES):
    ts = (DAY_START + c * 300) * 1000
    out = []
    for d in range(N_DEV):
      for i in range(N_INTF):
        tags = f"ip={ip(d)} intf={i}"
        base = (d * 40 + i) % 997
        for k, m in enumerate(METRICS):
          v = round(base * (k + 1) + 50 * math.sin((c + i) / 12.0), 3)
          out.append(f"{m} {ts} {v} {tags}")
    yield ("\n".join(out) + "\n").encode()


QUERIES = {
  "1 series, raw (288 pts)":
    dict(metric="in_bw", aggregator="sum", tags={"ip": ip(7), "intf": "3"}, explicitTags=True),
  "1 series, 1h-avg":
    dict(metric="in_bw", aggregator="sum", downsample="1h-avg", tags={"ip": ip(7), "intf": "3"}, explicitTags=True),
  "1 device, 40 series grouped, 5m-sum":
    dict(metric="in_bw", aggregator="sum", downsample="5m-sum", tags={"ip": ip(7), "intf": "*"}),
  "1 device total (40 series summed), 1h-sum":
    dict(metric="in_bw", aggregator="sum", downsample="1h-sum", tags={"ip": ip(7)}),
  "1 device, p95 per intf, 1h":
    dict(metric="in_bw", aggregator="sum", downsample="1h-p95", tags={"ip": ip(7), "intf": "*"}),
  "1 device, fill zero (Python agg), 5m-avg":
    dict(metric="in_bw", aggregator="sum", downsample="5m-avg-zero", tags={"ip": ip(7), "intf": "*"}),
  "10 devices regexp, per device, 1h-max":
    dict(metric="in_bw", aggregator="max", downsample="1h-max",
         filters=[{"type": "regexp", "tagk": "ip", "filter": r"^10\.0\.1[0-9]\.1$", "groupBy": True}]),
  "whole metric total (10k series), 1h-sum":
    dict(metric="in_bw", aggregator="sum", downsample="1h-sum"),
  "whole metric, every series (none), 1d-avg":
    dict(metric="in_bw", aggregator="none", downsample="1d-avg"),
  "whole metric total, raw 5m (no downsample)":
    dict(metric="in_bw", aggregator="sum"),
}


def digest(res, tol_round=6) -> str:
  norm = sorted(json.dumps({"t": r["tags"], "a": r["aggregateTags"],
                            "d": {k: (None if v is None else round(v, tol_round)) for k, v in r["dps"].items()}},
                           sort_keys=True) for r in res)
  return hashlib.sha1("\n".join(norm).encode()).hexdigest()[:12]


def points_of(res) -> int:
  return sum(len(r["dps"]) for r in res)


async def bench(backend: str) -> dict:
  os.environ["TSDB_BACKEND"] = backend
  config.get_settings.cache_clear()
  s = config.get_settings().model_copy(update={"pg_maintenance_interval_s": 0, "tsdb_query_timeout_s": 600,
                                               "tsdb_max_points": 50_000_000, "tsdb_max_body": 1 << 40})
  out: dict = {"backend": backend}

  # fresh schema
  await drop(backend, s)
  await migrate.migrate("tsdb_bench")
  store = make_store(s)
  await store.open()
  try:
    # ---- ingest
    async def chunks():
      for c in gen():
        yield c
    r = IngestResult()
    t = time.perf_counter()
    await ingest_stream(chunks(), store, s, SeriesCache(2_000_000), r)
    dt = time.perf_counter() - t
    out["ingest"] = {"points": r.success, "failed": r.failed, "seconds": round(dt, 1),
                     "lines_per_s": round(r.success / dt)}
    print(f"[{backend}] ingest {r.success:,} in {dt:.1f}s = {r.success / dt:,.0f}/s", flush=True)

    # ---- re-ingest one cycle (idempotency cost, ~70k lines that already exist)
    first = next(gen())
    async def one():
      yield first
    r2 = IngestResult()
    t = time.perf_counter()
    await ingest_stream(one(), store, s, SeriesCache(2_000_000), r2)
    out["reingest_cycle_s"] = round(time.perf_counter() - t, 2)

    # ---- settle: merge / vacuum so sizes and planner stats are real
    t = time.perf_counter()
    if backend == "clickhouse":
      await ch.client().command("OPTIMIZE TABLE tsdb_bench.points FINAL")
    else:
      async with store.pool.acquire() as conn:
        await conn.execute("SET statement_timeout = 0")
        await conn.execute("VACUUM ANALYZE tsdb_bench.points")
        await conn.execute("ANALYZE tsdb_bench.series")
        await conn.execute("ANALYZE tsdb_bench.series_tag")
    out["settle_s"] = round(time.perf_counter() - t, 1)
    st = await store.stats()
    if backend == "postgres":
      async with store.pool.acquire() as conn:
        total = await conn.fetchval(
          "SELECT sum(pg_total_relation_size(c.oid)) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
          "WHERE n.nspname = 'tsdb_bench' AND c.relkind IN ('r', 'p')")
        heap = await conn.fetchval(
          "SELECT sum(pg_relation_size(i.inhrelid)) FROM pg_inherits i WHERE i.inhparent = 'tsdb_bench.points'::regclass")
      out["storage"] = {"points_bytes": st["disk_bytes"], "points_heap_bytes": int(heap), "all_tables_bytes": int(total)}
    else:
      total = (await ch.client().query(
        "SELECT sum(bytes_on_disk) FROM system.parts WHERE database = 'tsdb_bench' AND active")).result_rows[0][0]
      out["storage"] = {"points_bytes": st["disk_bytes"], "points_uncompressed_bytes": st["uncompressed_bytes"],
                        "all_tables_bytes": int(total)}
    out["storage"]["bytes_per_point"] = round(st["disk_bytes"] / r.success, 2)
    print(f"[{backend}] storage {out['storage']}", flush=True)

    # ---- queries
    out["queries"] = {}
    for name, q in QUERIES.items():
      req = QueryIn(start=START, end=END, queries=[q])
      times = []
      t = time.perf_counter()
      res = await run_query(store, s, req)
      first_ms = (time.perf_counter() - t) * 1000
      for _ in range(REPS):
        t = time.perf_counter()
        await run_query(store, s, req)
        times.append((time.perf_counter() - t) * 1000)
      times.sort()
      out["queries"][name] = {"first_ms": round(first_ms, 1), "median_ms": round(statistics.median(times), 1),
                              "p95_ms": round(times[int(len(times) * 0.95) - 1], 1),
                              "groups": len(res), "points": points_of(res), "digest": digest(res),
                              "digest_3dp": digest(res, 3)}
      print(f"[{backend}] {name}: median {statistics.median(times):.1f} ms ({len(res)} groups, "
            f"{points_of(res)} pts)", flush=True)

    # ---- concurrency: 32 single-series dashboard queries at once
    reqs = [QueryIn(start=START, end=END, queries=[dict(metric="in_bw", aggregator="sum", downsample="5m-avg",
                    tags={"ip": ip(d), "intf": str(d % 40)}, explicitTags=True)]) for d in range(32)]
    t = time.perf_counter()
    await asyncio.gather(*(run_query(store, s, rq) for rq in reqs))
    out["concurrent_32_single_series_ms"] = round((time.perf_counter() - t) * 1000, 1)

    t = time.perf_counter()
    for _ in range(REPS):
      await store.suggest("tagv", "10.1.", 25, "in_bw", "ip")
    out["suggest_tagv_ms"] = round((time.perf_counter() - t) * 1000 / REPS, 1)
  finally:
    await drop(backend, s, store)
    await store.close()
  return out


async def drop(backend, s, store=None):
  if backend == "clickhouse":
    c = await ch.open_client(s.model_copy(update={"ch_database": "default"})) if store is None else ch.client()
    await c.command("DROP DATABASE IF EXISTS tsdb_bench")
    if store is None:
      await ch.close_client()
  else:
    import asyncpg
    conn = await asyncpg.connect(s.pg_url, user=s.pg_user, password=s.pg_password or None)
    await conn.execute("DROP SCHEMA IF EXISTS tsdb_bench CASCADE")
    await conn.close()


async def main():
  results = [await bench("clickhouse"), await bench("postgres")]
  with open(sys.argv[1], "w") as f:
    json.dump(results, f, indent=1)


asyncio.run(main())
