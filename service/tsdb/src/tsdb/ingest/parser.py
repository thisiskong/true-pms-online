"""OpenTSDB line format: `<metric> <timestamp> <value> <tagk=tagv> [<tagk=tagv> ...]`."""
import math
import re
import unicodedata
from dataclasses import dataclass

# OpenTSDB's charset [A-Za-z0-9-_./] plus Unicode letters, digits and combining marks.
NAME_RE = re.compile(r"[\w\-./]+")
MS_THRESHOLD = 9_999_999_999          # above this a timestamp is in milliseconds
MAX_TS_MS = 9_999_999_999_999         # 13 digits


class LineError(ValueError):
  pass


@dataclass(slots=True)
class Point:
  metric: str
  tags: dict[str, str]
  canonical: str
  ts_ms: int
  value: float


def valid_name(s: str) -> bool:
  if NAME_RE.fullmatch(s) is not None:
    return True
  # Slow path: also allow combining marks (Thai vowels and tone marks are category M*, not \w).
  return bool(s) and all(c.isalnum() or c in "-_./" or unicodedata.category(c)[0] == "M" for c in s)


def canonical_series(metric: str, tags: dict[str, str]) -> str:
  """Stable text form of a series: metric, then tags sorted by key, NUL-separated."""
  return "\x00".join([metric, *(f"{k}={tags[k]}" for k in sorted(tags))])


def _parse_tags(tag_str: str, max_tags: int) -> tuple[dict[str, str], str]:
  """`k=v k2=v2 ...` -> (tags, canonical tail). Raises LineError."""
  tag_parts = tag_str.split()
  if len(tag_parts) > max_tags:
    raise LineError(f"too many tags ({len(tag_parts)} > {max_tags})")
  tags: dict[str, str] = {}
  for p in tag_parts:
    k, sep, v = p.partition("=")
    if not sep or not k or not v:
      raise LineError(f"invalid tag {p!r}, expected tagk=tagv")
    if not valid_name(k) or not valid_name(v):
      raise LineError(f"invalid characters in tag {p!r}")
    if k in tags:
      raise LineError(f"duplicate tag key {k!r}")
    tags[k] = v
  return tags, "\x00".join(f"{k}={tags[k]}" for k in sorted(tags))


class LineParser:
  """Parses lines for one request. Pollers repeat the same tag string for every metric of an
  interface, so validated tag strings and metric names are cached (bounded)."""

  CACHE_MAX = 200_000

  def __init__(self, min_ms: int, max_ms: int, max_tags: int):
    self.min_ms, self.max_ms, self.max_tags = min_ms, max_ms, max_tags
    self._metrics: set[str] = set()
    self._tags: dict[str, tuple[dict[str, str], str]] = {}

  def __call__(self, line: str) -> Point:
    parts = line.split(None, 3)
    if len(parts) < 3:
      raise LineError("expected '<metric> <timestamp> <value> <tagk=tagv> ...'")
    if len(parts) < 4:
      raise LineError("at least one tag is required")
    metric, ts_s, val_s, tag_str = parts

    if metric not in self._metrics:
      if not valid_name(metric):
        raise LineError(f"invalid metric name {metric!r}")
      if len(self._metrics) >= self.CACHE_MAX:
        self._metrics.clear()
      self._metrics.add(metric)

    if not ts_s.isascii() or not ts_s.isdigit():
      raise LineError(f"invalid timestamp {ts_s!r}")
    ts = int(ts_s)
    ts_ms = ts if ts > MS_THRESHOLD else ts * 1000
    if ts_ms > MAX_TS_MS:
      raise LineError(f"invalid timestamp {ts_s!r}")
    if ts_ms > self.max_ms:
      raise LineError("timestamp is in the future")
    if ts_ms < self.min_ms:
      raise LineError("timestamp is older than the retention period")

    if "_" in val_s:
      raise LineError(f"value is not a number: {val_s!r}")
    try:
      value = float(val_s)
    except ValueError:
      raise LineError(f"value is not a number: {val_s!r}") from None
    if not math.isfinite(value):
      raise LineError("value must be finite (NaN and Inf are not accepted)")

    cached = self._tags.get(tag_str)
    if cached is None:
      cached = _parse_tags(tag_str, self.max_tags)    # errors are not cached: they raise
      if len(self._tags) >= self.CACHE_MAX:
        self._tags.clear()
      self._tags[tag_str] = cached
    tags, tail = cached
    return Point(metric, tags, metric + "\x00" + tail, ts_ms, value)


def parse_line(line: str, min_ms: int, max_ms: int, max_tags: int) -> Point:
  return LineParser(min_ms, max_ms, max_tags)(line)
