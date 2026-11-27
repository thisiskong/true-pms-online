"""Postgres backend: daily range partitions, upsert on (series_id, ts), no extensions needed.

Writes go through per-connection temp tables: COPY the batch in (binary), then one INSERT ... SELECT
... ON CONFLICT per table. Duplicates inside a batch are collapsed (the last line wins) before the
upsert, and a re-sent point with an unchanged value is not rewritten.
"""
import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import orjson

from ..migrate import rename
from ..query.parse import QueryError
from . import Series, Store
from . import pg_sql
from .pg_sql import like_escape, to_signed, to_unsigned

log = logging.getLogger("tsdb.postgres")

SQL_DIR = Path(__file__).resolve().parents[3] / "sql" / "postgres"
DAY_MS = 86_400_000
PARTITION_PREFIX = "points_"

TEMP_TABLES = """
CREATE TEMP TABLE IF NOT EXISTS _tsdb_series
  (series_id bigint, metric text, tags jsonb, n_tags smallint) ON COMMIT DELETE ROWS;
CREATE TEMP TABLE IF NOT EXISTS _tsdb_points
  (ord int, series_id bigint, ts_ms bigint, value float8) ON COMMIT DELETE ROWS;
"""


def _day_name(day: int) -> str:
  return PARTITION_PREFIX + datetime.fromtimestamp(day * 86400, UTC).strftime("%Y%m%d")


def _name_day(name: str) -> int | None:
  try:
    d = datetime.strptime(name.removeprefix(PARTITION_PREFIX), "%Y%m%d").replace(tzinfo=UTC)
  except ValueError:
    return None
  return int(d.timestamp()) // 86400


class PostgresStore(Store):
  name = "postgres"

  def __init__(self, s):
    super().__init__(s)
    self.schema = s.pg_schema
    self.pool: asyncpg.Pool | None = None
    self._parts: set[int] = set()     # days whose partition this worker knows exists
    self._maint_task: asyncio.Task | None = None

  # ---- lifecycle -----------------------------------------------------------------------------

  async def open(self) -> None:
    async def init(conn):
      await conn.execute(TEMP_TABLES)

    self.pool = await asyncpg.create_pool(
      self.s.pg_url, user=self.s.pg_user, password=self.s.pg_password or None,
      min_size=1, max_size=self.s.pg_pool_size, init=init,
      server_settings={"statement_timeout": str(self.s.tsdb_query_timeout_s * 1000),
                       "application_name": "tsdb"},
    )
    if self.s.pg_maintenance_interval_s > 0:
      self._maint_task = asyncio.create_task(self._maintenance_loop())

  async def close(self) -> None:
    if self._maint_task is not None:
      self._maint_task.cancel()
      try:
        await self._maint_task
      except asyncio.CancelledError:
        pass
      self._maint_task = None
    if self.pool is not None:
      await self.pool.close()
      self.pool = None

  async def ping(self) -> bool:
    return await self.pool.fetchval("SELECT 1") == 1

  async def migrate(self, database: str) -> None:
    self.schema = database
    async with self.pool.acquire() as conn:
      for f in sorted(SQL_DIR.glob("*.sql")):
        await conn.execute(rename(f.read_text(encoding="utf-8"), database))   # one script per file
        print(f"postgres/{f.name}: applied to schema {database}")
    await self.maintain()        # create the partitions for the coming days

  # ---- partitions and maintenance ------------------------------------------------------------

  def _key(self, what: str) -> str:
    return f"tsdb:{self.schema}:{what}"

  async def _ensure_partitions(self, days) -> None:
    missing = sorted(set(days) - self._parts)
    if not missing:
      return
    async with self.pool.acquire() as conn, conn.transaction():
      # Serializes partition DDL across workers, so CREATE ... IF NOT EXISTS never races.
      await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", self._key("ddl"))
      for day in missing:
        lo = datetime.fromtimestamp(day * 86400, UTC)
        hi = lo + timedelta(days=1)
        await conn.execute(
          f"CREATE TABLE IF NOT EXISTS {self.schema}.{_day_name(day)} PARTITION OF {self.schema}.points "
          f"FOR VALUES FROM ('{lo.isoformat()}') TO ('{hi.isoformat()}')")
    self._parts.update(missing)

  async def _partitions(self, conn) -> list[tuple[str, int, int, int]]:
    """(name, total bytes, heap bytes, live rows estimate) of every partition of points."""
    rows = await conn.fetch(
      "SELECT c.relname, pg_total_relation_size(c.oid), pg_relation_size(c.oid), "
      "coalesce(st.n_live_tup, 0) FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
      "LEFT JOIN pg_stat_user_tables st ON st.relid = c.oid "
      "WHERE i.inhparent = to_regclass($1)", f"{self.schema}.points")
    return [tuple(r) for r in rows]

  async def maintain(self) -> None:
    """Pre-create partitions, drop expired ones, apply per-metric retention. One worker at a time."""
    today = int(time.time()) // 86400
    await self._ensure_partitions(range(today - 1, today + 3))
    async with self.pool.acquire() as conn:
      if not await conn.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", self._key("maintain")):
        return                     # another worker is on it (the lock is released when the pool resets)
      try:
        await conn.execute("SET statement_timeout = 0; SET lock_timeout = '10s'")
        cutoff_ms = int(time.time() * 1000) - self.s.tsdb_max_retention_days * DAY_MS
        for name, *_ in await self._partitions(conn):
          day = _name_day(name)
          if day is not None and (day + 1) * DAY_MS <= cutoff_ms:     # every point in it is expired
            async with conn.transaction():
              await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", self._key("ddl"))
              await conn.execute(f"DROP TABLE IF EXISTS {self.schema}.{name}")
            self._parts.discard(day)
            log.info("dropped expired partition %s.%s", self.schema, name)
        for like, days in await conn.fetch(f"SELECT metric_like, days FROM {self.schema}.retention"):
          status = await conn.execute(
            f"DELETE FROM {self.schema}.points p USING {self.schema}.series s "
            "WHERE p.series_id = s.series_id AND s.metric LIKE $1 AND p.ts < now() - $2 * interval '1 day'",
            like, days)
          if status != "DELETE 0":
            log.info("retention %r (%d days): %s", like, days, status)
      finally:
        await conn.execute("SELECT pg_advisory_unlock(hashtext($1))", self._key("maintain"))

  async def _maintenance_loop(self) -> None:
    while True:
      try:
        await self.maintain()
      except asyncio.CancelledError:
        raise
      except Exception:
        log.exception("maintenance failed; retrying in %d s", self.s.pg_maintenance_interval_s)
      await asyncio.sleep(self.s.pg_maintenance_interval_s)

  # ---- ingest --------------------------------------------------------------------------------

  async def write(self, new_series, cols) -> None:
    _, sids, ts, vals = cols
    days = {t // DAY_MS for t in ts}
    await self._ensure_partitions(days)
    try:
      await self._write(new_series, sids, ts, vals)
    except asyncpg.exceptions.CheckViolationError as e:
      if "no partition" not in str(e):
        raise
      self._parts.clear()          # a partition was dropped behind this worker's back
      await self._ensure_partitions(days)
      await self._write(new_series, sids, ts, vals)

  async def _write(self, new_series, sids, ts, vals) -> None:
    sc = self.schema
    async with self.pool.acquire() as conn, conn.transaction():
      if new_series:
        await conn.copy_records_to_table(
          "_tsdb_series", columns=["series_id", "metric", "tags", "n_tags"],
          records=[(to_signed(sid), m, orjson.dumps(tags).decode(), len(tags))
                   for sid, (m, tags) in new_series.items()])
        await conn.execute(
          f"INSERT INTO {sc}.series (series_id, metric, tags, n_tags) "
          "SELECT series_id, metric, tags, n_tags FROM _tsdb_series "
          "ON CONFLICT (series_id) DO UPDATE SET updated_at = now()")
        await conn.execute(
          f"INSERT INTO {sc}.series_tag (metric, tag_key, tag_value, series_id) "
          "SELECT n.metric, kv.key, kv.value, n.series_id FROM _tsdb_series n, jsonb_each_text(n.tags) kv "
          "ON CONFLICT DO NOTHING")
      await conn.copy_records_to_table(
        "_tsdb_points", columns=["ord", "series_id", "ts_ms", "value"],
        records=zip(range(len(ts)), map(to_signed, sids), ts, vals))
      await conn.execute(
        f"INSERT INTO {sc}.points AS p (series_id, ts, value) "
        f"SELECT DISTINCT ON (series_id, ts_ms) series_id, {pg_sql.EPOCH} + ts_ms * interval '1 millisecond', value "
        "FROM _tsdb_points ORDER BY series_id, ts_ms, ord DESC "
        "ON CONFLICT (series_id, ts) DO UPDATE SET value = EXCLUDED.value, ingested_at = EXCLUDED.ingested_at "
        "WHERE p.value IS DISTINCT FROM EXCLUDED.value")

  # ---- query ---------------------------------------------------------------------------------

  async def resolve(self, metric, filters, explicit, limit) -> list[Series]:
    sql, params = pg_sql.resolve_sql(self.schema, metric, filters, explicit, limit)
    try:
      rows = await self.pool.fetch(sql, *params)
    except asyncpg.exceptions.InvalidRegularExpressionError as e:
      raise QueryError(f"invalid regexp: {e}") from None
    return sorted(((to_unsigned(sid), orjson.loads(tags)) for sid, tags in rows), key=lambda r: r[0])

  async def points(self, metric, ids, groups, start_ms, end_ms, ds, aggregator, dedup, limit) -> list[tuple]:
    # `dedup` needs no work here: the primary key keeps one row per (series_id, ts).
    sql, params = pg_sql.points_sql(self.schema, [to_signed(i) for i in ids], groups, start_ms, end_ms,
                                    ds, aggregator, limit)
    rows = await self.pool.fetch(sql, *params)
    if groups is None:
      return [(to_unsigned(sid), b, v) for sid, b, v in rows]
    return [tuple(r) for r in rows]

  async def suggest(self, type, q, max, metric, tagk) -> list[str]:
    sc = self.schema
    params: list = [like_escape(q) + "%", max]
    if type == "metrics":
      sql = f"SELECT DISTINCT metric FROM {sc}.series WHERE metric LIKE $1 ORDER BY 1 LIMIT $2"
    else:
      col = "tag_key" if type == "tagk" else "tag_value"
      where = [f"{col} LIKE $1"]
      if metric:
        params.append(metric)
        where.append(f"metric = ${len(params)}")
      if type == "tagv" and tagk:
        params.append(tagk)
        where.append(f"tag_key = ${len(params)}")
      sql = f"SELECT DISTINCT {col} FROM {sc}.series_tag WHERE {' AND '.join(where)} ORDER BY 1 LIMIT $2"
    return [r[0] for r in await self.pool.fetch(sql, *params)]

  async def stats(self) -> dict:
    sc = self.schema
    async with self.pool.acquire() as conn:
      parts = await self._partitions(conn)
    series_sql = f"SELECT metric, count(*) FROM {sc}.series GROUP BY metric"
    keys_sql = f"SELECT metric, array_agg(DISTINCT tag_key) FROM {sc}.series_tag GROUP BY metric"
    recent_sql = (
      f"SELECT s.metric, count(*), (extract(epoch FROM max(p.ts)) * 1000)::bigint, "
      f"(extract(epoch FROM max(p.ingested_at)) * 1000)::bigint "
      f"FROM {sc}.points p JOIN {sc}.series s USING (series_id) "
      f"WHERE p.ts >= now() - interval '1 day' GROUP BY s.metric"
    )
    series, keys, recent = await asyncio.gather(
      self.pool.fetch(series_sql), self.pool.fetch(keys_sql), self.pool.fetch(recent_sql))
    used = sorted(n.removeprefix(PARTITION_PREFIX) for n, _, heap, _ in parts if heap > 0)
    disk = sum(p[1] for p in parts)
    return {
      "rows": sum(p[3] for p in parts),     # estimate from pg_stat_user_tables (exact count is a scan)
      "disk_bytes": disk,
      "uncompressed_bytes": disk,           # heap storage is not compressed
      "parts": len(parts),
      "days": len(used),
      "first_day": used[0] if used else None,
      "last_day": used[-1] if used else None,
      "series": [tuple(r) for r in series], "keys": [tuple(r) for r in keys], "recent": [tuple(r) for r in recent],
    }
