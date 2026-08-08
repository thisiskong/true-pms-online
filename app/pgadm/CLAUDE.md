# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small utility repo built around `export_schema.py`, a script that connects to a PostgreSQL
database and dumps its schema (tables, views, materialized views, sequences — DDL, columns,
constraints, indexes, partition clauses, sequence parameters) to `.sql` files on disk, organized as
`tables/`, `views/`, `mviews/`, `sequences/` under an output directory. `diff_schema.py` is a
companion tool that compares two such exported snapshot folders and generates the SQL delta between
them. `main.py` is an unrelated placeholder entrypoint (`uv run python main.py` just prints a hello
message) and is not part of the export tool.

## Commands

Dependencies and running are managed with `uv` (see `pyproject.toml` / `uv.lock`).

Run the schema export against a database:

```
uv run python export_schema.py --host <host> --port 5432 --dbname <db> --user <user> --output <dir>
```

- `--password` can be passed inline; if omitted it is prompted interactively via `getpass`.
- `--schema` defaults to `public`.
- `--tables` restricts export to a comma-separated list of table/view/matview/sequence names
  (default: all).
- Output directory gets `tables/`, `views/`, `mviews/`, `sequences/` subfolders created under it,
  each populated with one `<schema>.<name>.sql` file per object.

`run.ps1` records the actual invocations used for this project's two environments (`dev` and `prd`),
each pointing at a different host/dbname/credentials and writing into the corresponding `dev/` or
`prd/` directory at the repo root — that's what those two directories are (schema snapshots, not
application code).

## Architecture of export_schema.py

The script queries PostgreSQL system catalogs directly (`pg_class`, `pg_namespace`, `pg_attribute`,
`pg_constraint`, `pg_indexes`, `pg_sequences`, etc.) rather than using introspection libraries —
everything needed to reconstruct DDL is fetched via raw SQL against `pg_catalog`. The flow for each
object kind (table, view, matview, sequence) is: list objects of that kind in the schema → fetch its
definition pieces (columns/constraints/partition/indexes for tables; `pg_get_viewdef` for
views/matviews; start/increment/min/max/cache/cycle from `pg_sequences` for sequences) → build a DDL
string → write it to its own file. Tables and matviews also get any non-constraint indexes appended
as separate `CREATE INDEX` statements in the same file.

Note: reconstructed table DDL is a best-effort approximation (column defaults/not-null +
constraints + partition clause) — it does not attempt to capture every possible PostgreSQL DDL
feature (e.g., table inheritance beyond partitioning, storage parameters, comments, grants).

## diff_schema.py

Compares two exported schema snapshots (folders in the layout produced by `export_schema.py`) and
writes the SQL needed to reconcile them:

```
uv run python diff_schema.py --source dev --target prd --output <dir>
```

- `--source` is the desired end state, `--target` is the state to be migrated; the generated SQL,
  run against a database currently matching `--target`, brings it in line with `--source`. Swap the
  two flags to get the opposite direction.
- Needs no database connection — it parses the already-exported `.sql` files back into a structured
  form (columns/constraints/partition/indexes for tables; body text for views/matviews; start/
  increment/min/max/cache/cycle for sequences), relying on the fact that `export_schema.py`'s output
  is deterministically formatted (one column/constraint/index per line).
- Output directory gets three files: `create.sql`, `modify.sql`, `drop.sql`, each statement preceded
  by a `-- <kind>: <schema>.<name>` comment. Tables get column/constraint/index-level ALTERs where
  possible; a differing partition clause can't be ALTERed in PostgreSQL, so it's surfaced as a
  `-- WARNING` comment in `modify.sql` instead. Materialized views have no `CREATE OR REPLACE`, so a
  changed matview is emitted as a single `DROP MATERIALIZED VIEW` + rebuild unit inside `modify.sql`
  (not split across `drop.sql`/`create.sql`).

## dev/ and prd/ directories

These hold the actual exported schema output for the "dev" (`dv01`/`pmsonline`) and "prd"
(`db01`/`pmsonline`) databases, checked in as a point-in-time reference of the live schema. They
are generated artifacts, not hand-maintained — regenerate them by re-running the commands in
`run.ps1` rather than editing the `.sql` files directly.
