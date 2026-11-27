# pms-infra (local dev)

Compose project `pms-infra`: ClickHouse and Postgres 18, each with the database named by `CH_DB` / `PG_DB` in `.env` (default `pmsonline`).

## Start

```powershell
cd deployment/infra
copy .env.example .env      # then set CH_PASSWORD and PG_PASSWORD
docker compose up -d
docker compose ps           # wait for both to be "healthy"
```

## Connect

| Service | Container | Host endpoint | Database | Credentials |
|---|---|---|---|---|
| ClickHouse HTTP | `clickhouse` | `http://localhost:18123` (SQL console: `/play`) | `CH_DB` | `CH_USER` / `CH_PASSWORD` |
| ClickHouse native | `clickhouse` | `localhost:19000` | `CH_DB` | same |
| Postgres | `postgres` | `localhost:15432` | `PG_DB` | `PG_USER` / `PG_PASSWORD` |

```powershell
docker compose exec clickhouse clickhouse-client --user pms --password <pw> -d pmsonline
docker compose exec postgres psql -U pms -d pmsonline
```

DSN: `postgresql://pms:<pw>@localhost:15432/pmsonline`

## Notes

- Data lives in the named volumes `pms-infra_ch-data`, `pms-infra_ch-logs` and `pms-infra_pg-data`. `docker compose down` keeps them; `down -v` deletes them.
- Databases are created from `CH_DB` and `PG_DB` by the images on first start. `clickhouse/initdb/*.sql` and `postgres/initdb/*.sql` run only on the first start with an empty data volume.
- Ports bind to `127.0.0.1` only. Host ports 8123 and 5432 are avoided on purpose: other local containers use them.
- ClickHouse: only `dev.xml` is mounted into `config.d`. Mounting the whole directory would hide the image's `docker_related_config.xml`, which sets `listen_host`.
- Postgres 18 keeps data in `/var/lib/postgresql/18/docker`, so the volume mounts at `/var/lib/postgresql`.
