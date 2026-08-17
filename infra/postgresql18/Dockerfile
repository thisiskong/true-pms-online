# PostgreSQL 18 + PostGIS + TimescaleDB + pg_stat_statements, for use with the
# CloudNativePG operator.
#
# Built FROM CNPG's own base image rather than plain postgres:18 — PGDG (needed
# for the postgresql-18-postgis-3 package) is already configured there, and CNPG's
# image-requirements (specific binaries on PATH, a version-parseable tag — never
# `latest`) are guaranteed to be satisfied. See:
#   https://cloudnative-pg.io/docs/1.28/container_images/
#
# Build & push yourself, then replace <REGISTRY_PLACEHOLDER> in
# overlays/{dev,prd}/cluster-patch.yaml with the real image reference:
#
#   docker build -t <REGISTRY>/pg18-postgis-tsdb:18 .
#   docker push <REGISTRY>/pg18-postgis-tsdb:18
#
# IMPORTANT: verify the current tag for ghcr.io/cloudnative-pg/postgresql before
# building (check https://github.com/cloudnative-pg/postgres-containers for
# current tags) and pin a specific one below — this Dockerfile's default may go
# stale. Never use `latest`; CNPG rejects it when parsing the major version.

ARG PG_MAJOR=18
ARG BASE=ghcr.io/cloudnative-pg/postgresql:18.3-standard-trixie
FROM ${BASE}

ARG PG_MAJOR
ARG POSTGIS_MAJOR=3
ARG TIMESCALEDB_APT_REPO=https://packagecloud.io/timescale/timescaledb

USER root

# PostGIS — PGDG is already configured in the CNPG base image, no extra repo needed.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      postgresql-${PG_MAJOR}-postgis-${POSTGIS_MAJOR} \
      postgresql-${PG_MAJOR}-postgis-${POSTGIS_MAJOR}-scripts && \
    apt-get purge -y --auto-remove && \
    rm -rf /var/lib/apt/lists/*

# TimescaleDB — NOT in PGDG, needs Timescale's own apt repo. Uses an explicit
# dearmored keyring + signed-by= (avoids legacy apt-key / Sequoia-PGP trust
# issues some newer apt versions hit with packagecloud's install script on
# Debian trixie). If this repo setup ever breaks on trixie, fall back to a
# -bookworm (Debian 12) tagged CNPG base image instead (change BASE above).
RUN . /etc/os-release && \
    apt-get update && apt-get install -y --no-install-recommends gnupg wget ca-certificates && \
    wget -qO- ${TIMESCALEDB_APT_REPO}/gpgkey | gpg --dearmor -o /usr/share/keyrings/timescaledb.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/timescaledb.gpg] ${TIMESCALEDB_APT_REPO}/debian/ ${VERSION_CODENAME}/main main" \
      > /etc/apt/sources.list.d/timescaledb.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      timescaledb-2-loader-postgresql-${PG_MAJOR} \
      timescaledb-2-postgresql-${PG_MAJOR} && \
    apt-get purge -y --auto-remove gnupg wget && \
    rm -rf /var/lib/apt/lists/*

# pg_stat_statements ships in contrib, already present in the CNPG base image —
# no extra package needed. It's enabled via shared_preload_libraries and
# CREATE EXTENSION in base/cluster.yaml, not here.

# No ENTRYPOINT/CMD override — CNPG's instance manager takes over regardless.
USER 26
