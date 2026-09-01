"""Environment-based configuration for the device MCP server.

Loads a local .env (if present) then reads settings from the environment.
Never hardcode credentials here — see .env.example for the expected keys.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str

    statement_timeout_ms: int

    default_network: str

    default_limit: int
    max_limit: int

    stats_default_top_n: int
    stats_max_top_n: int


def _env_int(name: str, default: str) -> int:
    return int(os.environ.get(name, default))


def load_settings() -> Settings:
    try:
        pg_password = os.environ["PGPASSWORD"]
    except KeyError as exc:
        raise RuntimeError(
            "PGPASSWORD is not set. Copy .env.example to .env and fill it in, "
            "or export the PG* vars before running the server."
        ) from exc

    return Settings(
        pg_host=os.environ.get("PGHOST", "dv01"),
        pg_port=_env_int("PGPORT", "5432"),
        pg_database=os.environ.get("PGDATABASE", "pmsonline"),
        pg_user=os.environ.get("PGUSER", "pmsonline_ro"),
        pg_password=pg_password,
        statement_timeout_ms=_env_int("PG_STATEMENT_TIMEOUT_MS", "5000"),
        default_network=os.environ.get("DEVICE_DEFAULT_NETWORK", "FTTx"),
        default_limit=_env_int("DEVICE_DEFAULT_LIMIT", "50"),
        max_limit=_env_int("DEVICE_MAX_LIMIT", "200"),
        stats_default_top_n=_env_int("DEVICE_STATS_DEFAULT_TOP_N", "20"),
        stats_max_top_n=_env_int("DEVICE_STATS_MAX_TOP_N", "100"),
    )
