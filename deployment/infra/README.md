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

## Copy the app tables from the remote pmsonline

`sync-app-tables.ps1` backs up the 9 tables the backend reads (`device`, `intf`, `intf_rev`, `device_uptime`, `ponport`, `ponport_rev`, `board`, `odn_onu`, `ticket`; about 13 GB, `onu_pon_1d` excluded) from the remote `pmsonline` and restores them into the local `postgres`. It needs the VPN for the backup step.

```powershell
cd deployment/infra
./sync-app-tables.ps1                            # backup + restore (asks before replacing local tables)
./sync-app-tables.ps1 -Mode backup               # dump only
./sync-app-tables.ps1 -Mode restore -Yes         # reload the newest dump, no VPN needed
./sync-app-tables.ps1 -Tables board,device_uptime -Yes   # subset, e.g. to test
```

- pg_dump / pg_restore run in a throwaway `postgres:18.6` container on the compose network (`postgres/sync-app-tables.sh`), so no local client is needed. Remote credentials come from `REMOTE_PG_DSN` in `backend/.env` (falling back to `PG_DSN`, refused if it points at the local database), local ones from this `.env`, and both reach the container only as environment variables.
- Backups: `postgres/.sync/<yyyyMMddTHHmm>/` (gitignored), directory format, zstd, plus `manifest.json`. A backup gets its final name only when complete. The newest 3 are kept (`-Keep`).
- Restore drops the selected local tables (`CASCADE`), restores data, then indexes and foreign keys, runs `ANALYZE` and prints local row counts against the remote estimates.
- With `PMSONLINE_RO_PASSWORD` set, a local `pmsonline_ro` role gets `SELECT` on these tables and `default_transaction_read_only = on`, like the remote. To run the backend against the local copy, set in `backend/.env`:
  `PG_DSN=postgresql://pmsonline_ro:<PMSONLINE_RO_PASSWORD>@localhost:15432/pmsonline`
- The remote is only read (its role is read-only). Remote owners and grants are not copied (`--no-owner --no-privileges`).

## Notes

- Data lives in the named volumes `pms-infra_ch-data`, `pms-infra_ch-logs` and `pms-infra_pg-data`. `docker compose down` keeps them; `down -v` deletes them.
- Databases are created from `CH_DB` and `PG_DB` by the images on first start. `clickhouse/initdb/*.sql` and `postgres/initdb/*.sql` run only on the first start with an empty data volume.
- Ports bind to `127.0.0.1` only. Host ports 8123 and 5432 are avoided on purpose: other local containers use them.
- ClickHouse: only `dev.xml` is mounted into `config.d`. Mounting the whole directory would hide the image's `docker_related_config.xml`, which sets `listen_host`.
- Postgres 18 keeps data in `/var/lib/postgresql/18/docker`, so the volume mounts at `/var/lib/postgresql`.
