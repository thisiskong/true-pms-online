"""ClickHouse client: one async client per worker process, shared by all requests."""
from urllib.parse import urlparse

import clickhouse_connect
from clickhouse_connect.driver.asyncclient import AsyncClient

from .config import Settings

_client: AsyncClient | None = None


async def open_client(s: Settings) -> AsyncClient:
  global _client
  u = urlparse(s.ch_url)
  _client = await clickhouse_connect.get_async_client(
    host=u.hostname or "localhost",
    port=u.port or (8443 if u.scheme == "https" else 8123),
    secure=u.scheme == "https",
    username=s.ch_user,
    password=s.ch_password,
    database=s.ch_database,
    # Sub-queries run concurrently: a shared session would serialize (and reject) them.
    autogenerate_session_id=False,
    # Series id arrays can be large: send parameters in the body, not the URL.
    form_encode_query_params=True,
    settings={"max_execution_time": s.tsdb_query_timeout_s},
  )
  return _client


async def close_client() -> None:
  global _client
  if _client is not None:
    await _client.close()
    _client = None


def client() -> AsyncClient:
  if _client is None:
    raise RuntimeError("ClickHouse client is not open")
  return _client
