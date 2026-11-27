"""Service settings, read from the environment (and an optional .env file)."""
import re
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class Settings(BaseSettings):
  model_config = SettingsConfigDict(env_file=".env", extra="ignore")

  tsdb_backend: Literal["clickhouse", "postgres"] = "clickhouse"

  ch_url: str = "http://localhost:18123"
  ch_user: str = "default"
  ch_password: str = ""
  ch_database: str = "tsdb"

  pg_url: str = "postgresql://localhost:15432/pmsonline"   # database; the tables live in pg_schema
  pg_user: str = "postgres"
  pg_password: str = ""
  pg_schema: str = "tsdb"
  pg_pool_size: int = 10                 # connections per worker
  pg_maintenance_interval_s: int = 3600  # partition upkeep and retention; 0 disables the loop

  tsdb_api_key: str = ""                 # empty disables the check (dev only)
  tsdb_max_retention_days: int = 400     # older points are rejected at ingest
  tsdb_future_tolerance_s: int = 600     # newer than now + this are rejected
  tsdb_max_tags: int = 8
  tsdb_max_body: int = 512 * 1024 * 1024  # uncompressed bytes
  tsdb_batch_rows: int = 200_000
  tsdb_series_cache: int = 1_000_000     # per worker
  tsdb_max_errors: int = 100             # errors listed in an ingest response
  tsdb_max_series_per_query: int = 20_000
  tsdb_max_points: int = 5_000_000       # per query response
  tsdb_query_concurrency: int = 8
  tsdb_query_timeout_s: int = 30

  @field_validator("ch_database", "pg_schema")
  @classmethod
  def _identifier(cls, v: str) -> str:
    # Interpolated into SQL as an identifier, so only plain names are allowed.
    if not IDENT_RE.fullmatch(v):
      raise ValueError(f"must be a plain identifier ([A-Za-z_][A-Za-z0-9_]*), got {v!r}")
    return v

  @property
  def database(self) -> str:
    """Namespace of the tsdb tables: the ClickHouse database or the Postgres schema."""
    return self.pg_schema if self.tsdb_backend == "postgres" else self.ch_database


@lru_cache
def get_settings() -> Settings:
  return Settings()
