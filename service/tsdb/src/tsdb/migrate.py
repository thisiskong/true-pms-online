"""Create or upgrade the schema of the configured backend (TSDB_BACKEND).

ClickHouse applies sql/*.sql; Postgres applies sql/postgres/*.sql. The files name the
database/schema `tsdb`; --database (default CH_DATABASE or PG_SCHEMA) renames it.

Usage: uv run tsdb-migrate [--database NAME]
"""
import argparse
import asyncio
import re

from .config import get_settings
from .store import make_store


def statements(text: str, database: str) -> list[str]:
  """ClickHouse: one statement per `;` (the ClickHouse files hold no `;` inside statements)."""
  body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("--"))
  return [st.strip() for st in rename(body, database).split(";") if st.strip()]


def rename(text: str, database: str) -> str:
  text = re.sub(r"\btsdb\.", f"{database}.", text)
  return re.sub(r"((?:DATABASE|SCHEMA) IF NOT EXISTS) tsdb\b", rf"\1 {database}", text)


async def migrate(database: str) -> None:
  # The ClickHouse database may not exist yet; the Postgres loop would run before the schema does.
  s = get_settings().model_copy(update={"ch_database": "default", "pg_maintenance_interval_s": 0})
  store = make_store(s)
  await store.open()
  try:
    await store.migrate(database)
  finally:
    await store.close()


def main() -> None:
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--database", default=get_settings().database)
  asyncio.run(migrate(ap.parse_args().database))


if __name__ == "__main__":
  main()
