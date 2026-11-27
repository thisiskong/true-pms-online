"""Step 3 of a sub-query: grouping, cross-series aggregation (Python path), fill and formatting."""
import statistics
from dataclasses import dataclass

from .parse import Downsample


@dataclass
class Group:
  key: tuple
  series: list[tuple[int, dict[str, str]]]   # (series_id, tags)


def make_groups(series: list[tuple[int, dict[str, str]]], group_keys: list[str],
                aggregator: str) -> list[Group]:
  if aggregator == "none":
    return [Group((sid,), [(sid, tags)]) for sid, tags in series]
  by_key: dict[tuple, Group] = {}
  for sid, tags in series:
    key = tuple(tags.get(k, "") for k in group_keys)
    by_key.setdefault(key, Group(key, [])).series.append((sid, tags))
  return [by_key[k] for k in sorted(by_key)]


def group_tags(g: Group) -> tuple[dict[str, str], list[str]]:
  """OpenTSDB: `tags` are keys with one value across the group, `aggregateTags` the rest."""
  all_keys: set[str] = set()
  for _, t in g.series:
    all_keys.update(t)
  common = {}
  for k in sorted(all_keys):
    vals = {t.get(k) for _, t in g.series}
    if len(vals) == 1 and None not in vals:
      common[k] = vals.pop()
  return common, sorted(all_keys - common.keys())


def fill_buckets(ds: Downsample | None, start_ms: int, end_ms: int) -> list[int] | None:
  """Every bucket of the range when the fill policy emits empty buckets, else None."""
  if ds is None or ds.fill == "none":
    return None
  if ds.interval_s == 0:
    return [start_ms]
  iv = ds.interval_s * 1000
  return list(range(start_ms - start_ms % iv, end_ms + 1, iv))


def bucket_count(ds: Downsample | None, start_ms: int, end_ms: int) -> int:
  if ds is None:
    return 0
  if ds.interval_s == 0:
    return 1
  iv = ds.interval_s * 1000
  return (end_ms - (start_ms - start_ms % iv)) // iv + 1


def _agg(aggregator: str, vals: list[float]) -> float | None:
  if not vals:
    return 0.0 if aggregator == "zimsum" else None
  if aggregator in ("sum", "zimsum"):
    return float(sum(vals))
  if aggregator == "avg":
    return sum(vals) / len(vals)
  if aggregator in ("min", "mimmin"):
    return min(vals)
  if aggregator in ("max", "mimmax"):
    return max(vals)
  if aggregator == "count":
    return float(len(vals))
  if aggregator == "dev":
    return statistics.pstdev(vals)
  if aggregator == "none":
    return vals[0]
  raise ValueError(aggregator)


def aggregate_python(g: Group, per_series: dict[int, dict[int, float]], aggregator: str,
                     ds: Downsample | None, buckets: list[int] | None) -> dict[int, float | None]:
  sids = [sid for sid, _ in g.series]
  zero = ds is not None and ds.fill == "zero"
  if buckets is None:
    keys = sorted({b for sid in sids for b in per_series.get(sid, {})})
  else:
    keys = buckets
  out: dict[int, float | None] = {}
  for b in keys:
    if zero:
      vals = [per_series.get(sid, {}).get(b, 0.0) for sid in sids]
    else:
      vals = [v for sid in sids if (v := per_series.get(sid, {}).get(b)) is not None]
    out[b] = _agg(aggregator, vals)
  return out


def apply_fill(dps: dict[int, float | None], buckets: list[int] | None, ds: Downsample | None) -> dict:
  if buckets is None:
    return dps
  empty = 0.0 if ds.fill == "zero" else None
  return {b: dps.get(b, empty) for b in buckets}


def format_dps(dps: dict[int, float | None], ms_resolution: bool, arrays: bool):
  items = sorted(dps.items())
  if not ms_resolution:
    sec: dict[int, float | None] = {}
    for b, v in items:
      sec[b // 1000] = v
    items = list(sec.items())
  if arrays:
    return [[b, v] for b, v in items]
  return {str(b): v for b, v in items}
