"""Parsing of OpenTSDB query parameters: times, downsample specs, aggregators and tag filters."""
import re
import time
from dataclasses import dataclass

from ..ingest.parser import MS_THRESHOLD, valid_name


class QueryError(ValueError):
  """Invalid query: reported to the client as HTTP 400."""


# ---- time -----------------------------------------------------------------------------------

UNIT_MS = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000,
           "w": 7 * 86_400_000, "n": 30 * 86_400_000, "y": 365 * 86_400_000}
RELATIVE_RE = re.compile(r"(\d+)(ms|s|m|h|d|w|n|y)-ago")


def parse_time(v: int | float | str | None, now_ms: int, name: str) -> int:
  """Epoch seconds or ms (number or numeric string), 'now', or '<n><unit>-ago'. Returns ms."""
  if v is None:
    return now_ms
  if isinstance(v, bool):
    raise QueryError(f"invalid {name}: {v!r}")
  if isinstance(v, (int, float)):
    n = int(v)
  else:
    s = v.strip()
    if s == "now":
      return now_ms
    m = RELATIVE_RE.fullmatch(s)
    if m:
      return now_ms - int(m.group(1)) * UNIT_MS[m.group(2)]
    if not s.isdigit():
      raise QueryError(f"invalid {name}: {v!r} (use epoch seconds/ms, 'now' or e.g. '1h-ago')")
    n = int(s)
  if n < 0:
    raise QueryError(f"invalid {name}: {v!r}")
  return n if n > MS_THRESHOLD else n * 1000


def now_ms() -> int:
  return int(time.time() * 1000)


# ---- downsample -----------------------------------------------------------------------------

FILLS = {"none", "nan", "null", "zero"}
DS_FUNCS = {"avg", "sum", "min", "max", "count", "first", "last", "dev"}
PCT_RE = re.compile(r"p(\d{2,3})")
DS_RE = re.compile(r"(\d+)([a-z]+)-([a-z0-9]+)(?:-([a-z]+))?")
DS_UNITS_S = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}


@dataclass(frozen=True)
class Downsample:
  interval_s: int          # 0 means "0all": one bucket for the whole range
  func: str
  fill: str


def parse_downsample(spec: str | None) -> Downsample | None:
  if spec is None or spec == "":
    return None
  m = DS_RE.fullmatch(spec.strip())
  if not m:
    raise QueryError(f"invalid downsample {spec!r}, expected e.g. '5m-avg' or '1h-sum-zero'")
  n, unit, func, fill = int(m.group(1)), m.group(2), m.group(3), m.group(4) or "none"
  if unit == "all":
    if n != 0:
      raise QueryError(f"invalid downsample {spec!r}: use '0all-<func>'")
    interval = 0
  elif unit in DS_UNITS_S:
    if n <= 0:
      raise QueryError(f"invalid downsample {spec!r}: interval must be > 0")
    interval = n * DS_UNITS_S[unit]
  elif unit in ("ms", "n", "y") or unit.endswith("c"):
    raise QueryError(f"downsample unit {unit!r} is not supported (use s, m, h, d, w or 0all)")
  else:
    raise QueryError(f"invalid downsample unit {unit!r}")
  if func not in DS_FUNCS and not PCT_RE.fullmatch(func):
    raise QueryError(f"unsupported downsample function {func!r}")
  if fill not in FILLS:
    raise QueryError(f"unsupported fill policy {fill!r} (use none, nan, null or zero)")
  return Downsample(interval, func, fill)


def percentile(func: str) -> float:
  digits = PCT_RE.fullmatch(func).group(1)
  return int(digits) / (10 ** len(digits))


# ---- aggregators ----------------------------------------------------------------------------

AGGREGATORS = {"sum", "avg", "min", "max", "count", "dev", "zimsum", "mimmin", "mimmax", "none"}


def check_aggregator(a: str) -> str:
  if a not in AGGREGATORS:
    raise QueryError(f"unsupported aggregator {a!r}; supported: {', '.join(sorted(AGGREGATORS))}")
  return a


# ---- tag filters ----------------------------------------------------------------------------

FILTER_TYPES = {"literal_or", "wildcard", "regexp", "not_literal_or"}


@dataclass(frozen=True)
class TagFilter:
  tagk: str
  type: str            # literal_or | wildcard | regexp | not_literal_or
  filter: str
  group_by: bool

  @property
  def values(self) -> list[str]:
    return self.filter.split("|")


def tags_to_filters(tags: dict[str, str]) -> list[TagFilter]:
  """OpenTSDB 2.2+ semantics for the `tags` map: every entry is a group-by filter."""
  out = []
  for k, v in tags.items():
    if v == "*" or "*" in v:
      out.append(TagFilter(k, "wildcard", v, True))
    else:
      out.append(TagFilter(k, "literal_or", v, True))
  return out


def check_filter(f: TagFilter) -> TagFilter:
  if f.type not in FILTER_TYPES:
    raise QueryError(f"unsupported filter type {f.type!r}; supported: {', '.join(sorted(FILTER_TYPES))}")
  if not valid_name(f.tagk):
    raise QueryError(f"invalid tag key {f.tagk!r}")
  if f.filter == "":
    raise QueryError(f"empty filter for tag key {f.tagk!r}")
  if f.type in ("literal_or", "not_literal_or") and any(v == "" for v in f.values):
    raise QueryError(f"empty value in filter {f.filter!r}")
  return f
