"""Connection pooling + defense-in-depth session setup.

Every checked-out connection is forced read-only and statement-timeout-bound
at the session level, on top of the pmsonline_ro role already being
SELECT-only at the DB-privilege level. Belt and suspenders against a runaway
or unexpected query — this server should never be able to write or hang.
"""

from __future__ import annotations

import contextlib
from typing import Iterator

import psycopg2
import psycopg2.extensions
import psycopg2.extras
import psycopg2.pool

from .config import Settings


class Database:
    def __init__(self, settings: Settings, minconn: int = 1, maxconn: int = 5) -> None:
        self._settings = settings
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn,
            maxconn,
            host=settings.pg_host,
            port=settings.pg_port,
            dbname=settings.pg_database,
            user=settings.pg_user,
            password=settings.pg_password,
        )

    @contextlib.contextmanager
    def cursor(self) -> Iterator["psycopg2.extras.RealDictCursor"]:
        conn = self._pool.getconn()
        try:
            # Reasserted on every checkout (not just once at pool creation) so
            # behavior doesn't depend on pool internals resetting session state.
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SET statement_timeout = %s",
                    (self._settings.statement_timeout_ms,),
                )
                yield cur
        finally:
            self._pool.putconn(conn)

    def close(self) -> None:
        self._pool.closeall()
