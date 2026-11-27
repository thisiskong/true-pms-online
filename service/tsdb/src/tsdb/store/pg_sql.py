"""SQL for the Postgres backend: series lookup (step 1) and points read/downsample/aggregate (step 2).

Same semantics as query/resolve.py and query/plan.py (ClickHouse), written for Postgres. Values are
always bound ($n), and identifiers come from validated settings, never from requests.
"""
import re
from collections import defaultdict

from ..query.parse import Downsample, QueryError, TagFilter, percentile

EPOCH = "timestamptz 'epoch'"
TS_MS = "(extract(epoch FROM ts) * 1000)::bigint"

SQL_AGGS = {"sum": "sum(ds)", "avg": "avg(ds)", "min": "min(ds)", "max": "max(ds)",
            "count": "count(*)::float8", "dev": "stddev_pop(ds)"}

DS_FUNCS = {"avg": "avg(v)", "sum": "sum(v)", "min": "min(v)", "max": "max(v)",
            "count": "count(*)::float8", "first": "(array_agg(v ORDER BY ts))[1]",
            "last": "(array_agg(v ORDER BY ts DESC))[1]", "dev": "stddev_pop(v)"}

U64 = 1 << 64
I63 = 1 << 63


def to_signed(sid: int) -> int:
  """Series ids are unsigned 64-bit; Postgres bigint is signed. Same bits, other reading."""
  return sid - U64 if sid >= I63 else sid


def to_unsigned(sid: int) -> int:
  return sid + U64 if sid < 0 else sid


class PgParams:
  """Collects bound parameters and returns `$n` placeholders (with a cast when given)."""

  def __init__(self):
    self.values: list = []

  def add(self, value, cast: str = "") -> str:
    self.values.append(value)
    return f"${len(self.values)}" + (f"::{cast}" if cast else "")


def like_escape(s: str) -> str:
  return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def wildcard_to_like(pattern: str) -> str:
  return like_escape(pattern).replace("*", "%")


def _value_condition_pg(f: TagFilter, p: PgParams) -> str | None:
  if f.type == "literal_or":
    return f"tag_value = ANY({p.add(f.values, 'text[]')})"
  if f.type == "wildcard":
    if set(f.filter) == {"*"}:
      return None
    return f"tag_value LIKE {p.add(wildcard_to_like(f.filter), 'text')}"
  if f.type == "regexp":
    try:
      re.compile(f.filter)
    except re.error as e:
      raise QueryError(f"invalid regexp {f.filter!r}: {e}") from None
    return f"tag_value ~ {p.add(f.filter, 'text')}"
  return None   # not_literal_or: only the key has to exist here; values are excluded later


def resolve_sql(schema: str, metric: str, filters: list[TagFilter], explicit: bool,
                limit: int) -> tuple[str, list]:
  p = PgParams()
  m = p.add(metric, "text")
  where = [f"s.metric = {m}"]

  by_key: dict[str, list[TagFilter]] = defaultdict(list)
  for f in filters:
    by_key[f.tagk].append(f)

  if by_key:
    row_conds = []
    for k, fs in by_key.items():
      conds = [f"tag_key = {p.add(k, 'text')}"]
      conds += [c for f in fs if (c := _value_condition_pg(f, p)) is not None]
      row_conds.append("(" + " AND ".join(conds) + ")")
    where.append(
      f"s.series_id IN (SELECT series_id FROM {schema}.series_tag WHERE metric = {m} "
      f"AND ({' OR '.join(row_conds)}) GROUP BY series_id HAVING count(DISTINCT tag_key) = {len(by_key)})"
    )
    for k, fs in by_key.items():
      for f in fs:
        if f.type == "not_literal_or":
          where.append(f"NOT (s.tags ->> {p.add(k, 'text')} = ANY({p.add(f.values, 'text[]')}))")
  elif explicit:
    raise QueryError("explicitTags requires at least one tag filter (every series has tags)")

  if explicit:
    where.append(f"s.n_tags = {len(by_key)}")

  sql = (f"SELECT s.series_id, s.tags FROM {schema}.series s WHERE {' AND '.join(where)} "
         f"LIMIT {int(limit) + 1}")
  return sql, p.values


def ds_expr(func: str) -> str:
  if func in DS_FUNCS:
    return DS_FUNCS[func]
  return f"percentile_cont({percentile(func)!r}) WITHIN GROUP (ORDER BY v)"


def points_sql(schema: str, ids: list[int], groups: list[int] | None, start_ms: int, end_ms: int,
               ds: Downsample | None, aggregator: str, limit: int) -> tuple[str, list]:
  """`ids` are signed (as stored). Rows: (group, bucket_ms, value) with `groups`, else
  (series_id, bucket_ms, value). Points are unique per (series_id, ts), so no dedup step."""
  p = PgParams()
  idp = p.add(ids, "bigint[]")
  s, e = p.add(start_ms, "bigint"), p.add(end_ms, "bigint")
  src = (f"SELECT series_id, ts, value AS v FROM {schema}.points WHERE series_id = ANY({idp}) "
         f"AND ts >= {EPOCH} + {s} * interval '1 millisecond' "
         f"AND ts <= {EPOCH} + {e} * interval '1 millisecond'")

  if ds is None:
    per_series = f"SELECT series_id, {TS_MS} AS bucket, v AS ds FROM ({src}) r"
  else:
    if ds.interval_s == 0:
      bucket = s
    else:
      iv = int(ds.interval_s) * 1000
      bucket = f"({TS_MS} / {iv}) * {iv}"
    per_series = (f"SELECT series_id, {bucket} AS bucket, {ds_expr(ds.func)} AS ds "
                  f"FROM ({src}) r GROUP BY series_id, bucket")

  if groups is not None:
    g = p.add(groups, "int[]")
    sql = (f"SELECT g.grp, d.bucket, {SQL_AGGS[aggregator]} AS val FROM ({per_series}) d "
           f"JOIN unnest({idp}, {g}) AS g(sid, grp) ON g.sid = d.series_id "
           f"GROUP BY g.grp, d.bucket ORDER BY 1, 2 LIMIT {int(limit) + 1}")
  else:
    sql = f"SELECT series_id, bucket, ds FROM ({per_series}) d ORDER BY 1, 2 LIMIT {int(limit) + 1}"
  return sql, p.values
