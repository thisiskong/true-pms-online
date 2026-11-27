"""Step 2 of a sub-query: read, dedup, downsample and (when possible) aggregate in ClickHouse."""
from .parse import Downsample, percentile
from .resolve import Params

# Cross-series aggregators whose "skip missing" semantics match a plain SQL GROUP BY.
SQL_AGGS = {"sum": "sum(ds)", "avg": "avg(ds)", "min": "min(ds)", "max": "max(ds)",
            "count": "toFloat64(count())", "dev": "stddevPop(ds)"}

DS_FUNCS = {"avg": "avg(v)", "sum": "sum(v)", "min": "min(v)", "max": "max(v)",
            "count": "toFloat64(count())", "first": "argMin(v, ts)", "last": "argMax(v, ts)",
            "dev": "stddevPop(v)"}


def aggregate_in_sql(aggregator: str, ds: Downsample | None) -> bool:
  return aggregator in SQL_AGGS and (ds is None or ds.fill != "zero")


def ds_expr(func: str) -> str:
  if func in DS_FUNCS:
    return DS_FUNCS[func]
  return f"quantile({percentile(func)!r})(v)"


SEL_TABLE = "_sel"
SEL_STRUCTURE = ["series_id UInt64", "grp UInt32"]


def sel_table(ids: list[int], groups: list[int] | None) -> bytes:
  """TSV body of the external table: one (series_id, group) row per selected series."""
  gs = groups if groups is not None else [0] * len(ids)
  return "".join(f"{i}\t{g}\n" for i, g in zip(ids, gs)).encode()


def points_sql(database: str, metric: str, ids: list[int], groups: list[int] | None,
               start_ms: int, end_ms: int, ds: Downsample | None, aggregator: str,
               dedup: bool, limit: int) -> tuple[str, dict]:
  """Rows are (group, bucket_ms, value) when `groups` is given (aggregated in SQL), else
  (series_id, bucket_ms, value) for aggregation in Python. `groups[i]` is the group of `ids[i]`.

  The selected series are not bound parameters: they are sent as the external table SEL_TABLE
  (see sel_table()), because ClickHouse caps a form field at 128 KB (http_max_field_value_size,
  read from the server profile), i.e. a few thousand ids."""
  p = Params()
  m = p.add(metric, "String")
  s, e = p.add(start_ms, "Int64"), p.add(end_ms, "Int64")
  where = (f"metric = {m} AND series_id IN (SELECT series_id FROM {SEL_TABLE}) "
           f"AND ts >= fromUnixTimestamp64Milli({s}, 'UTC') AND ts <= fromUnixTimestamp64Milli({e}, 'UTC')")
  if dedup:
    src = (f"SELECT series_id, ts, argMax(value, ingested_at) AS v FROM {database}.points "
           f"WHERE {where} GROUP BY series_id, ts")
  else:
    src = f"SELECT series_id, ts, value AS v FROM {database}.points WHERE {where}"

  if ds is None:
    per_series = f"SELECT series_id, toUnixTimestamp64Milli(ts) AS bucket, v AS ds FROM ({src})"
  else:
    if ds.interval_s == 0:
      bucket = f"toInt64({s})"
    else:
      bucket = f"intDiv(toUnixTimestamp64Milli(ts), {p.add(ds.interval_s * 1000, 'Int64')}) * {ds.interval_s * 1000}"
    per_series = (f"SELECT series_id, {bucket} AS bucket, {ds_expr(ds.func)} AS ds "
                  f"FROM ({src}) GROUP BY series_id, bucket")

  if groups is not None:
    sql = (f"SELECT sel.grp AS g, bucket, {SQL_AGGS[aggregator]} AS val FROM ({per_series}) AS d "
           f"INNER JOIN {SEL_TABLE} AS sel ON sel.series_id = d.series_id "
           f"GROUP BY g, bucket ORDER BY g, bucket LIMIT {int(limit) + 1}")
  else:
    sql = f"SELECT series_id, bucket, ds FROM ({per_series}) ORDER BY series_id, bucket LIMIT {int(limit) + 1}"
  return sql, p.values
