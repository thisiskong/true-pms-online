"""Columnar batches of points, written through the storage backend: new series first, then points."""
from .parser import Point
from .series import SeriesCache, series_id

POINT_COLUMNS = ["metric", "series_id", "ts", "value"]
SERIES_COLUMNS = ["metric", "series_id", "tags"]
DAY_MS = 86_400_000
MAX_DAYS_PER_INSERT = 50   # ClickHouse rejects inserts touching > 100 partitions by default


class CollisionError(ValueError):
  pass


class Batch:
  def __init__(self, cache: SeriesCache):
    self.cache = cache
    self.metric: list[str] = []
    self.series_id: list[int] = []
    self.ts: list[int] = []
    self.value: list[float] = []
    self.new_series: dict[int, tuple[str, dict[str, str]]] = {}

  def __len__(self) -> int:
    return len(self.ts)

  def add(self, p: Point) -> None:
    sid = series_id(p.canonical)
    known = self.cache.lookup(sid)
    if known is None:
      if sid not in self.new_series:
        self.new_series[sid] = (p.metric, p.tags)
        self.cache.add(sid, p.canonical)
    elif known != p.canonical:
      raise CollisionError("series id collision with another series; point rejected")
    self.metric.append(p.metric)
    self.series_id.append(sid)
    self.ts.append(p.ts_ms)
    self.value.append(p.value)

  def clear(self) -> None:
    self.metric, self.series_id, self.ts, self.value = [], [], [], []
    self.new_series = {}

  async def flush(self, store) -> int:
    """Write the batch. Returns the number of points written. On failure the new series are
    dropped from the cache again, so a retry registers them."""
    n = len(self)
    if n == 0:
      return 0
    try:
      await store.write(self.new_series, [self.metric, self.series_id, self.ts, self.value])
    except Exception:
      self.cache.discard(self.new_series)
      raise
    finally:
      self.clear()
    return n

  def _chunks_by_day(self):
    return chunks_by_day([self.metric, self.series_id, self.ts, self.value])


def chunks_by_day(cols: list[list]):
  """Split [metric, series_id, ts_ms, value] columns so no chunk spans MAX_DAYS_PER_INSERT days."""
  ts = cols[2]
  days = {t // DAY_MS for t in ts}
  if len(days) <= MAX_DAYS_PER_INSERT:
    yield cols
    return
  order = sorted(range(len(ts)), key=ts.__getitem__)
  start = 0
  while start < len(order):
    first_day = ts[order[start]] // DAY_MS
    end = start
    while end < len(order) and ts[order[end]] // DAY_MS < first_day + MAX_DAYS_PER_INSERT:
      end += 1
    idx = order[start:end]
    yield [[c[i] for i in idx] for c in cols]
    start = end
