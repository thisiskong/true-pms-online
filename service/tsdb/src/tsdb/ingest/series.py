"""Series ids (64-bit hash of the canonical series) and the per-worker cache of registered series."""
import time

import xxhash


def series_id(canonical: str) -> int:
  return xxhash.xxh3_64_intdigest(canonical.encode())


class SeriesCache:
  """Ids this worker has already written to tsdb.series, mapped to their canonical form.

  Only an optimization: writing a known series again is harmless (ReplacingMergeTree). The
  canonical form is kept so a hash collision inside this process is detected. The cache is
  cleared when full and once a day, so series.updated_at is refreshed for live series.
  """

  def __init__(self, max_size: int):
    self.max_size = max_size
    self._ids: dict[int, str] = {}
    self._day = self._today()

  @staticmethod
  def _today() -> int:
    return int(time.time() // 86400)

  def lookup(self, sid: int) -> str | None:
    today = self._today()
    if today != self._day or len(self._ids) >= self.max_size:
      self._ids.clear()
      self._day = today
    return self._ids.get(sid)

  def add(self, sid: int, canonical: str) -> None:
    self._ids[sid] = canonical

  def discard(self, sids) -> None:
    for sid in sids:
      self._ids.pop(sid, None)

  def __len__(self) -> int:
    return len(self._ids)
