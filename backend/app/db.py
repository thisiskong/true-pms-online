"""Read-only asyncpg pool.

Every connection is opened with default_transaction_read_only=on and a
statement_timeout, on top of the pmsonline_ro role's SELECT-only grants.
"""
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg

from app.config import get_settings

_pool: asyncpg.Pool | None = None


async def open_pool() -> asyncpg.Pool:
  global _pool
  if _pool is None:
    s = get_settings()
    _pool = await asyncpg.create_pool(
      dsn=s.pg_dsn,
      min_size=s.pg_pool_min,
      max_size=s.pg_pool_max,
      command_timeout=s.pg_statement_timeout_ms / 1000 + 5,
      server_settings={
        "default_transaction_read_only": "on",
        "statement_timeout": str(s.pg_statement_timeout_ms),
        "application_name": "pms-proto",
      },
    )
  return _pool


async def close_pool() -> None:
  global _pool
  if _pool is not None:
    await _pool.close()
    _pool = None


def pool() -> asyncpg.Pool:
  if _pool is None:
    raise RuntimeError("DB pool is not open")
  return _pool


async def fetch(sql: str, *args: Any) -> list[asyncpg.Record]:
  return await pool().fetch(sql, *args)


async def fetchrow(sql: str, *args: Any) -> asyncpg.Record | None:
  return await pool().fetchrow(sql, *args)


async def fetchval(sql: str, *args: Any) -> Any:
  return await pool().fetchval(sql, *args)


@asynccontextmanager
async def readonly_cursor(sql: str, *args: Any, prefetch: int = 2000) -> AsyncIterator[Any]:
  """Server-side cursor inside an explicit READ ONLY transaction (for streaming exports)."""
  async with pool().acquire() as conn:
    async with conn.transaction(readonly=True):
      yield conn.cursor(sql, *args, prefetch=prefetch)
