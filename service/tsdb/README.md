# tsdb

Time-series metrics service: OpenTSDB-style ingest and query API on ClickHouse or Postgres (`TSDB_BACKEND`). Design: [DESIGN.md](DESIGN.md).

## Run (local dev)

Needs the ClickHouse from `deployment/infra` (`docker compose up -d` there).

```powershell
cd service/tsdb
copy .env.example .env          # set CH_USER / CH_PASSWORD (same as deployment/infra/.env)
uv sync
uv run tsdb-migrate             # creates database tsdb (idempotent)
uv run uvicorn tsdb.main:app --app-dir src --port 8080
```

Production: `--workers N` (each worker parses on its own core; about 250k lines/s per worker end to end).

### Postgres instead of ClickHouse

Set `TSDB_BACKEND=postgres` and `PG_URL` / `PG_USER` / `PG_PASSWORD`. The Postgres from `deployment/infra` works: `postgresql://localhost:15432/pmsonline`. The tables go into schema `PG_SCHEMA` (default `tsdb`), which `uv run tsdb-migrate` creates. It needs plain Postgres 16+ with no extensions. The API and the results are the same.

Postgres is faster for single-series and per-device queries but 10–17× slower for metric-wide scans. It ingests about 2.5× slower and needs about 21× more disk (103 vs 5 bytes per point). It fits small and medium installs; full traffic5m scale belongs on ClickHouse. See [BENCHMARK.md](BENCHMARK.md).

## Ingest

```bash
# raw body (plain or gzip)
curl -X POST localhost:8080/api/ingest -H 'Content-Type: text/plain' --data-binary @traffic5m.tsdb
curl -X POST localhost:8080/api/ingest --data-binary @traffic5m.tsdb.gz

# file upload (plain or .gz)
curl -X POST localhost:8080/api/ingest -F file=@traffic5m.tsdb.gz
```

Line format: `<metric> <timestamp s|ms> <value> <tagk=tagv> ...`. Response: `{"success": n, "failed": m, "errors": [...]}`, 200 when every line was stored, 400 when some lines were rejected (valid lines are still stored). Re-sending a file is harmless.

## Query

```bash
# POST (JSON body as in OpenTSDB)
curl -X POST localhost:8080/api/query -H 'Content-Type: application/json' -d '{
  "start": "1d-ago",
  "queries": [{ "metric": "in_bw", "aggregator": "sum", "downsample": "5m-avg-nan",
                "tags": { "ip": "10.163.193.127", "intf": "2" }, "explicitTags": true }]}'

# GET (OpenTSDB URL syntax; -g stops curl from interpreting the braces)
curl -g 'localhost:8080/api/query?start=1d-ago&end=now&m=avg:1h-max-nan:explicit_tags:in_bw{ip=10.163.193.127,intf=2}'
```

Also: `GET /api/health`, `GET /api/suggest?type=metrics|tagk|tagv&q=…`, `GET /api/stats`.

## Frontend

The main app has a **Metrics** page (`/metrics`): overview, metric list and a query explorer with charts. The explorer can chart up to 10 metrics at once, either on one chart with an optional right-hand axis or as split charts with linked zoom. It sends them as one `POST /api/query` with `showQuery` and uses `query.index` to tell results apart. In dev, Vite proxies `/tsdb/*` to this service on `http://localhost:8080`, so start it on that port.

## Tests

```bash
uv run pytest                  # unit tests; end-to-end tests need CH_* and/or PG_* credentials
```

The end-to-end tests run once per backend. They create and drop a separate ClickHouse database and Postgres schema `tsdb_test`; `tsdb` is not touched. A backend that is unreachable is skipped.
