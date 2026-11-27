"""Run a POST /api/query request: validate everything, then execute sub-queries concurrently."""
import asyncio
from dataclasses import dataclass

from ..config import Settings
from ..ingest.parser import valid_name
from . import assemble
from .models import QueryIn, SubQueryIn
from .parse import (Downsample, QueryError, TagFilter, check_aggregator, check_filter, now_ms,
                    parse_downsample, parse_time, tags_to_filters)
from .plan import aggregate_in_sql


@dataclass
class SubQuery:
  src: SubQueryIn
  metric: str
  aggregator: str
  ds: Downsample | None
  filters: list[TagFilter]
  explicit: bool

  @property
  def group_keys(self) -> list[str]:
    keys: list[str] = []
    for f in self.filters:
      if f.group_by and f.tagk not in keys:
        keys.append(f.tagk)
    return keys


def validate(q: SubQueryIn) -> SubQuery:
  if not valid_name(q.metric):
    raise QueryError(f"invalid metric name {q.metric!r}")
  if q.rate:
    raise QueryError("rate is not supported yet")
  filters = tags_to_filters(q.tags) + [
    TagFilter(f.tagk, f.type, f.filter, f.groupBy) for f in q.filters
  ]
  for f in filters:
    check_filter(f)
  return SubQuery(q, q.metric, check_aggregator(q.aggregator), parse_downsample(q.downsample),
                  filters, q.explicitTags)


async def run_subquery(store, s: Settings, sq: SubQuery, start_ms: int, end_ms: int,
                       req: QueryIn) -> list[dict]:
  series = await store.resolve(sq.metric, sq.filters, sq.explicit, s.tsdb_max_series_per_query)
  if len(series) > s.tsdb_max_series_per_query:
    raise QueryError(f"query for {sq.metric!r} matches more than {s.tsdb_max_series_per_query} series; "
                     "narrow the tag filters")
  if not series:
    return []
  groups = assemble.make_groups(series, sq.group_keys, sq.aggregator)

  buckets = assemble.fill_buckets(sq.ds, start_ms, end_ms)
  n_buckets = assemble.bucket_count(sq.ds, start_ms, end_ms)
  if n_buckets and n_buckets * len(groups) > s.tsdb_max_points:
    raise QueryError(f"query for {sq.metric!r} would return about {n_buckets * len(groups)} points "
                     f"(limit {s.tsdb_max_points}); use a coarser downsample or a shorter range")

  ids = [sid for sid, _ in series]
  in_sql = aggregate_in_sql(sq.aggregator, sq.ds)
  gidx = None
  if in_sql:
    index = {sid: i for i, g in enumerate(groups) for sid, _ in g.series}
    gidx = [index[sid] for sid in ids]
  data = await store.points(sq.metric, ids, gidx, start_ms, end_ms, sq.ds, sq.aggregator, req.dedup,
                            s.tsdb_max_points)
  if len(data) > s.tsdb_max_points:
    raise QueryError(f"query for {sq.metric!r} returns more than {s.tsdb_max_points} points; "
                     "use a downsample or a shorter range")

  if in_sql:
    per_group: dict[int, dict[int, float]] = {}
    for g, b, v in data:
      per_group.setdefault(g, {})[int(b)] = float(v)
    results = [(g, per_group[i]) for i, g in enumerate(groups) if i in per_group]
  else:
    per_series: dict[int, dict[int, float]] = {}
    for sid, b, v in data:
      per_series.setdefault(int(sid), {})[int(b)] = float(v)
    results = [(g, assemble.aggregate_python(g, per_series, sq.aggregator, sq.ds, buckets))
               for g in groups if any(sid in per_series for sid, _ in g.series)]

  out = []
  for g, dps in results:      # groups without any point in the range are left out, as in OpenTSDB
    tags, agg_tags = assemble.group_tags(g)
    item = {
      "metric": sq.metric,
      "tags": tags,
      "aggregateTags": agg_tags,
      "dps": assemble.format_dps(assemble.apply_fill(dps, buckets, sq.ds), req.msResolution, req.arrays),
    }
    if req.showQuery:
      item["query"] = sq.src.model_dump()
    out.append(item)
  return out


async def run_query(store, s: Settings, req: QueryIn) -> list[dict]:
  now = now_ms()
  start_ms = parse_time(req.start, now, "start")
  end_ms = parse_time(req.end, now, "end")
  if start_ms > end_ms:
    raise QueryError("start must not be after end")
  subs = [validate(q) for q in req.queries]      # all 400s before any query runs

  sem = asyncio.Semaphore(s.tsdb_query_concurrency)

  async def one(sq: SubQuery):
    async with sem:
      return await run_subquery(store, s, sq, start_ms, end_ms, req)

  parts = await asyncio.gather(*(one(sq) for sq in subs))
  if req.showQuery:     # like OpenTSDB: say which sub-query each result came from
    for i, part in enumerate(parts):
      for item in part:
        item["query"]["index"] = i
  return [item for part in parts for item in part]
