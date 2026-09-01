"""Low-cardinality reference data, exposed as MCP resources.

These ground the model in real filter values (actual vendor/region/olttype/
network strings) instead of it guessing free text and silently matching zero
rows. Cheap GROUP BY queries, TTL-cached so repeated resource reads don't
keep hitting Postgres.
"""

from __future__ import annotations

import time
from typing import Callable

from .db import Database

_TTL_SECONDS = 600


class _TTLCache:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._value: list[dict] | None = None
        self._expires_at = 0.0

    def get(self, loader: Callable[[], list[dict]]) -> list[dict]:
        now = time.monotonic()
        if self._value is None or now >= self._expires_at:
            self._value = loader()
            self._expires_at = now + self._ttl
        return self._value


_vendor_cache = _TTLCache(_TTL_SECONDS)
_region_cache = _TTLCache(_TTL_SECONDS)
_olttype_cache = _TTLCache(_TTL_SECONDS)
_network_cache = _TTLCache(_TTL_SECONDS)


def _distinct_counts(db: Database, column: str) -> list[dict]:
    # column is always one of the hardcoded names below, never user input.
    sql = f"""
        SELECT {column} AS value, count(*) AS device_count
        FROM device
        GROUP BY {column}
        ORDER BY device_count DESC
    """
    with db.cursor() as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def vendor_counts(db: Database) -> list[dict]:
    return _vendor_cache.get(lambda: _distinct_counts(db, "vendor"))


def region_counts(db: Database) -> list[dict]:
    return _region_cache.get(lambda: _distinct_counts(db, "region"))


def olttype_counts(db: Database) -> list[dict]:
    return _olttype_cache.get(lambda: _distinct_counts(db, "olttype"))


def network_counts(db: Database) -> list[dict]:
    return _network_cache.get(lambda: _distinct_counts(db, "network"))
