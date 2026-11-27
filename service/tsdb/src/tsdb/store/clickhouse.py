"""ClickHouse backend: ReplacingMergeTree tables, dedup at query time (see DESIGN.md)."""
import asyncio
from pathlib import Path

from clickhouse_connect.driver.external import ExternalData

from .. import ch
from ..ingest.writer import POINT_COLUMNS, SERIES_COLUMNS, chunks_by_day
from ..query.parse import Downsample, TagFilter
from ..query.plan import SEL_STRUCTURE, SEL_TABLE, points_sql, sel_table
from ..query.resolve import resolve_sql
from . import Series, Store

SQL_DIR = Path(__file__).resolve().parents[3] / "sql"


class ClickHouseStore(Store):
  name = "clickhouse"

  async def open(self) -> None:
    await ch.open_client(self.s)

  async def close(self) -> None:
    await ch.close_client()

  async def ping(self) -> bool:
    return await ch.client().ping()

  async def migrate(self, database: str) -> None:
    from ..migrate import statements
    for f in sorted(SQL_DIR.glob("*.sql")):
      sts = statements(f.read_text(encoding="utf-8"), database)
      for st in sts:
        await ch.client().command(st)
      print(f"{f.name}: {len(sts)} statement(s)")

  async def write(self, new_series, cols) -> None:
    c, db = ch.client(), self.s.ch_database
    if new_series:   # series first, so a point is never queryable without its series
      rows = [[m, sid, tags] for sid, (m, tags) in new_series.items()]
      await c.insert("series", rows, column_names=SERIES_COLUMNS, database=db)
    for chunk in chunks_by_day(cols):
      await c.insert("points", chunk, column_names=POINT_COLUMNS, database=db, column_oriented=True)

  async def resolve(self, metric: str, filters: list[TagFilter], explicit: bool, limit: int) -> list[Series]:
    sql, params = resolve_sql(self.s.ch_database, metric, filters, explicit, limit)
    rows = (await ch.client().query(sql, parameters=params)).result_rows
    return [(int(sid), dict(tags)) for sid, tags in rows]

  async def points(self, metric, ids, groups, start_ms, end_ms, ds: Downsample | None, aggregator, dedup,
                   limit) -> list[tuple]:
    sql, params = points_sql(self.s.ch_database, metric, ids, groups, start_ms, end_ms, ds, aggregator,
                             dedup, limit)
    sel = ExternalData(file_name=SEL_TABLE, data=sel_table(ids, groups), fmt="TabSeparated",
                       structure=SEL_STRUCTURE)
    return (await ch.client().query(sql, parameters=params, external_data=sel)).result_rows

  async def suggest(self, type, q, max, metric, tagk) -> list[str]:
    db = self.s.ch_database
    params: dict = {"q": q, "max": max}
    if type == "metrics":
      sql = (f"SELECT DISTINCT metric AS v FROM {db}.series WHERE startsWith(metric, {{q:String}}) "
             "ORDER BY v LIMIT {max:UInt32}")
    else:
      col = "tag_key" if type == "tagk" else "tag_value"
      where = [f"startsWith({col}, {{q:String}})"]
      if metric:
        where.append("metric = {metric:String}")
        params["metric"] = metric
      if type == "tagv" and tagk:
        where.append("tag_key = {tagk:String}")
        params["tagk"] = tagk
      sql = (f"SELECT DISTINCT {col} AS v FROM {db}.series_tag WHERE {' AND '.join(where)} "
             "ORDER BY v LIMIT {max:UInt32}")
    rows = (await ch.client().query(sql, parameters=params)).result_rows
    return [r[0] for r in rows]

  async def stats(self) -> dict:
    c, db = ch.client(), self.s.ch_database
    parts_sql = (
      "SELECT sum(rows), sum(bytes_on_disk), sum(data_uncompressed_bytes), count(), uniqExact(partition), "
      "min(partition), max(partition) FROM system.parts "
      "WHERE database = {db:String} AND table = 'points' AND active"
    )
    series_sql = f"SELECT metric, uniqExact(series_id) AS n FROM {db}.series GROUP BY metric"
    keys_sql = f"SELECT metric, groupUniqArray(tag_key) FROM {db}.series_tag GROUP BY metric"
    # Last 24 h only, so partition pruning keeps this cheap at any table size. Row counts include
    # duplicates that background merges have not collapsed yet.
    recent_sql = (
      f"SELECT metric, count(), toUnixTimestamp64Milli(max(ts)), toUnixTimestamp64Milli(max(ingested_at)) "
      f"FROM {db}.points WHERE ts >= now64(3) - INTERVAL 1 DAY GROUP BY metric"
    )
    parts, series, keys, recent = await asyncio.gather(
      c.query(parts_sql, parameters={"db": db}), c.query(series_sql), c.query(keys_sql), c.query(recent_sql))
    rows, disk, raw, n_parts, n_days, first_day, last_day = parts.result_rows[0]
    return {
      "rows": int(rows or 0), "disk_bytes": int(disk or 0), "uncompressed_bytes": int(raw or 0),
      "parts": int(n_parts or 0), "days": int(n_days or 0),
      "first_day": first_day or None, "last_day": last_day or None,
      "series": series.result_rows, "keys": keys.result_rows, "recent": recent.result_rows,
    }
