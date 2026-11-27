-- TSDB schema for the Postgres backend (see ../../DESIGN.md "Postgres backend").
-- Idempotent: safe to run again. `tsdb` is renamed to PG_SCHEMA (or --database) by tsdb-migrate.
-- Plain Postgres 16+ (developed on 18); no extensions needed.

CREATE SCHEMA IF NOT EXISTS tsdb;

-- One row per series (metric + tag set). series_id is the xxh3_64 id read as signed bigint.
CREATE TABLE IF NOT EXISTS tsdb.series
(
  series_id  bigint PRIMARY KEY,
  metric     text COLLATE "C" NOT NULL,
  tags       jsonb NOT NULL,
  n_tags     smallint NOT NULL,                  -- for explicitTags
  updated_at timestamptz NOT NULL DEFAULT now()  -- refreshed when a worker first sees it each day
);
CREATE INDEX IF NOT EXISTS series_metric_idx ON tsdb.series (metric);

-- Inverted tag index: (metric, key, value) -> series_id. Written together with series.
CREATE TABLE IF NOT EXISTS tsdb.series_tag
(
  metric    text COLLATE "C" NOT NULL,
  tag_key   text COLLATE "C" NOT NULL,
  tag_value text COLLATE "C" NOT NULL,
  series_id bigint NOT NULL,
  PRIMARY KEY (metric, tag_key, tag_value, series_id)
);
CREATE INDEX IF NOT EXISTS series_tag_kv_idx ON tsdb.series_tag (tag_key, tag_value);

-- One row per data point; the primary key makes (series_id, ts) unique, last write wins (upsert).
-- Daily range partitions points_YYYYMMDD (UTC) are created by the service on demand and dropped
-- after TSDB_MAX_RETENTION_DAYS by its maintenance loop.
CREATE TABLE IF NOT EXISTS tsdb.points
(
  series_id   bigint NOT NULL,
  ts          timestamptz NOT NULL,
  value       float8 NOT NULL,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (series_id, ts)
) PARTITION BY RANGE (ts);

-- Per-metric retention shorter than TSDB_MAX_RETENTION_DAYS (the maintenance loop deletes older
-- points of matching metrics). Metrics without a rule are kept for TSDB_MAX_RETENTION_DAYS.
-- Example: INSERT INTO tsdb.retention VALUES ('nokia\_%', 30), ('in_err', 90);
CREATE TABLE IF NOT EXISTS tsdb.retention
(
  metric_like text COLLATE "C" PRIMARY KEY,   -- LIKE pattern on the metric name
  days        integer NOT NULL CHECK (days > 0)
);
