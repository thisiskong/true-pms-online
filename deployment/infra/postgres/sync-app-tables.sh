#!/usr/bin/env bash
# Back up the app's tables from the remote pmsonline and restore them into the local Docker pmsonline.
# Runs inside a throwaway postgres:18.6 container on the compose network (see sync-app-tables.ps1).
#
# Environment (set by the wrapper; secrets come only from here, never from arguments):
#   SYNC_MODE            full | backup | restore
#   SYNC_TABLES          space-separated table names in schema public
#   SYNC_STAMP           backup directory name for a new backup (backup/full)
#   SYNC_FROM            backup directory name to restore (restore/full)
#   SYNC_JOBS            parallel jobs for pg_dump / pg_restore
#   SYNC_REMOTE_DSN      libpq URI of the remote (read-only role)
#   SYNC_LOCAL_HOST/PORT/DB/USER/PASSWORD   local superuser connection
#   SYNC_RO_PASSWORD     optional: password for the local read-only role pmsonline_ro
set -euo pipefail

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '[%s] ERROR: %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

rpsql() { psql "$SYNC_REMOTE_DSN" -X -v ON_ERROR_STOP=1 -At "$@"; }
lpsql() {
  PGPASSWORD="$SYNC_LOCAL_PASSWORD" psql -h "$SYNC_LOCAL_HOST" -p "$SYNC_LOCAL_PORT" -U "$SYNC_LOCAL_USER" \
    -d "$SYNC_LOCAL_DB" -X -v ON_ERROR_STOP=1 -At "$@"
}

for t in $SYNC_TABLES; do
  [[ "$t" =~ ^[a-z_][a-z0-9_]*$ ]] || die "invalid table name: $t"
done
in_list=$(printf "'%s'," $SYNC_TABLES); in_list=${in_list%,}
qualified=$(printf 'public.%s,' $SYNC_TABLES); qualified=${qualified%,}
dump_flags=(); for t in $SYNC_TABLES; do dump_flags+=(-t "public.$t"); done

preflight() {
  if [[ "$SYNC_MODE" != restore ]]; then
    log "remote: $(rpsql -c "select current_user || ' @ PostgreSQL ' || current_setting('server_version')")"
  fi
  log "local:  $(lpsql -c "select current_user || ' @ PostgreSQL ' || current_setting('server_version') || ', db ' || current_database()")"
}

backup() {
  local dir="/sync/$SYNC_STAMP"
  [[ -e "$dir" ]] && die "backup $dir already exists"
  rm -rf "$dir.partial"

  local found
  found=$(rpsql -c "select count(*) from pg_class where relnamespace = 'public'::regnamespace and relkind in ('r','p') and relname in ($in_list)")
  [[ "$found" == "$(wc -w <<<"$SYNC_TABLES")" ]] || die "remote has only $found of the requested tables: $SYNC_TABLES"
  local est
  est=$(rpsql -c "select json_object_agg(relname, greatest(reltuples, 0)::bigint) from pg_class
                  where relnamespace = 'public'::regnamespace and relname in ($in_list)")

  log "backup: $(wc -w <<<"$SYNC_TABLES") table(s), $SYNC_JOBS jobs -> $dir"
  # Directory format: parallel, compressed, restorable table by table. No owners or grants from the remote.
  pg_dump "$SYNC_REMOTE_DSN" --format=directory --jobs="$SYNC_JOBS" --compress=zstd:3 \
    --no-owner --no-privileges "${dump_flags[@]}" --file="$dir.partial"

  local tables_json
  tables_json=$(printf '"%s",' $SYNC_TABLES); tables_json="[${tables_json%,}]"
  cat > "$dir.partial/manifest.json" <<EOF
{
  "created_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "tables": $tables_json,
  "remote_server_version": "$(rpsql -c 'show server_version')",
  "remote_row_estimates": $est,
  "pg_dump": "$(pg_dump --version)"
}
EOF
  mv "$dir.partial" "$dir"      # only complete backups get a final name
  log "backup done: $(du -sh "$dir" | cut -f1)"
}

restore() {
  local dir="/sync/$SYNC_FROM"
  [[ -f "$dir/toc.dat" && -f "$dir/manifest.json" ]] || die "no complete backup at $dir"

  log "restore: $dir -> local $SYNC_LOCAL_DB"
  # CASCADE also drops foreign keys that local tables outside this set have on these tables (reported as NOTICE).
  lpsql -c "drop table if exists $qualified cascade"
  PGPASSWORD="$SYNC_LOCAL_PASSWORD" pg_restore -h "$SYNC_LOCAL_HOST" -p "$SYNC_LOCAL_PORT" -U "$SYNC_LOCAL_USER" \
    -d "$SYNC_LOCAL_DB" --jobs="$SYNC_JOBS" --no-owner --no-privileges --exit-on-error "$dir"
  log "analyze"
  lpsql -c "analyze $qualified"

  if [[ -n "${SYNC_RO_PASSWORD:-}" ]]; then
    log "local read-only role pmsonline_ro: SELECT on $(wc -w <<<"$SYNC_TABLES") table(s)"
    lpsql -v tables="$qualified" -v db="$SYNC_LOCAL_DB" <<'SQL'
\getenv ro_pw SYNC_RO_PASSWORD
SELECT NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pmsonline_ro') AS create_role \gset
\if :create_role
CREATE ROLE pmsonline_ro LOGIN;
\endif
ALTER ROLE pmsonline_ro WITH LOGIN PASSWORD :'ro_pw';
ALTER ROLE pmsonline_ro SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE :"db" TO pmsonline_ro;
GRANT USAGE ON SCHEMA public TO pmsonline_ro;
GRANT SELECT ON :tables TO pmsonline_ro;
SQL
  else
    log "PMSONLINE_RO_PASSWORD not set: skipping the local read-only role"
  fi

  verify "$dir/manifest.json"
}

verify() {
  local est
  est=$(tr -d '\n' < "$1" | sed -E 's/.*"remote_row_estimates": *(\{[^}]*\}).*/\1/')
  log "verify: local exact rows vs remote estimate at backup time"
  printf '  %-16s %14s %14s %8s\n' table local remote_est diff
  local warn=0
  for t in $SYNC_TABLES; do
    local row
    row=$(lpsql -F ' ' -c "select count(*), coalesce(('$est'::json ->> '$t')::bigint, 0) from public.$t")
    read -r n e <<<"$row"
    local pct="n/a"
    if (( e > 0 )); then
      pct=$(( (n - e) * 100 / e ))
      (( pct > 10 || pct < -10 )) && warn=1
      pct="${pct}%"
    fi
    printf '  %-16s %14s %14s %8s\n' "$t" "$n" "$e" "$pct"
  done
  (( warn )) && log "note: a difference above 10% usually means stale remote statistics, not a failed restore"
  return 0
}

preflight
case "$SYNC_MODE" in
  backup)  backup ;;
  restore) restore ;;
  full)    backup; SYNC_FROM="$SYNC_STAMP" restore ;;
  *)       die "unknown SYNC_MODE: $SYNC_MODE" ;;
esac
log "done"
