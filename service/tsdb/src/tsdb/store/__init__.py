"""Storage backends. One store per worker process, chosen by TSDB_BACKEND (clickhouse | postgres).

The ingest pipeline and the query engine only talk to the `Store` interface. Each backend turns
the same requests into its own SQL, so results are identical whichever backend holds the data.
"""
from abc import ABC, abstractmethod

from ..config import Settings
from ..query.parse import Downsample, TagFilter

Series = tuple[int, dict[str, str]]        # (series_id as unsigned 64-bit, tags)


class Store(ABC):
  name: str

  def __init__(self, s: Settings):
    self.s = s

  @abstractmethod
  async def open(self) -> None: ...

  @abstractmethod
  async def close(self) -> None: ...

  @abstractmethod
  async def ping(self) -> bool: ...

  @abstractmethod
  async def migrate(self, database: str) -> None:
    """Create or upgrade the schema in `database` (ClickHouse database / Postgres schema)."""

  @abstractmethod
  async def write(self, new_series: dict[int, tuple[str, dict[str, str]]], cols: list[list]) -> None:
    """Store new series, then points. `cols` is [metric[], series_id[], ts_ms[], value[]].
    Writing a known series or an existing (series, ts) again must be harmless: last write wins."""

  @abstractmethod
  async def resolve(self, metric: str, filters: list[TagFilter], explicit: bool, limit: int) -> list[Series]:
    """Series of `metric` matching every filter, at most `limit + 1` (so the caller sees overflow)."""

  @abstractmethod
  async def points(self, metric: str, ids: list[int], groups: list[int] | None, start_ms: int, end_ms: int,
                   ds: Downsample | None, aggregator: str, dedup: bool, limit: int) -> list[tuple]:
    """(group, bucket_ms, value) rows when `groups` is given (aggregated in the database), else
    (series_id, bucket_ms, value) rows. At most `limit + 1` rows."""

  @abstractmethod
  async def suggest(self, type: str, q: str, max: int, metric: str | None, tagk: str | None) -> list[str]: ...

  @abstractmethod
  async def stats(self) -> dict:
    """Storage overview for GET /api/stats (see api/meta.py for the shape)."""


_store: Store | None = None


def make_store(s: Settings) -> Store:
  if s.tsdb_backend == "postgres":
    from .postgres import PostgresStore
    return PostgresStore(s)
  from .clickhouse import ClickHouseStore
  return ClickHouseStore(s)


async def open_store(s: Settings) -> Store:
  global _store
  _store = make_store(s)
  await _store.open()
  return _store


async def close_store() -> None:
  global _store
  if _store is not None:
    await _store.close()
    _store = None


def get_store() -> Store:
  if _store is None:
    raise RuntimeError("storage is not open")
  return _store
