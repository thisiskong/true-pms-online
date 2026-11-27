-- TSDB schema (see ../DESIGN.md). Idempotent: safe to run again.

CREATE DATABASE IF NOT EXISTS tsdb;

-- One row per data point. Last write wins on (metric, series_id, ts).
CREATE TABLE IF NOT EXISTS tsdb.points
(
  metric      LowCardinality(String),
  series_id   UInt64,
  ts          DateTime64(3, 'UTC')  CODEC(DoubleDelta, ZSTD(1)),
  value       Float64               CODEC(Gorilla, ZSTD(1)),
  ingested_at DateTime64(3, 'UTC')  DEFAULT now64(3) CODEC(DoubleDelta, ZSTD(1))
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMMDD(ts)
ORDER BY (metric, series_id, ts)
TTL toDateTime(ts) + INTERVAL 400 DAY DELETE;

-- One row per series (metric + tag set).
CREATE TABLE IF NOT EXISTS tsdb.series
(
  metric     LowCardinality(String),
  series_id  UInt64,
  tags       Map(LowCardinality(String), String),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (metric, series_id);

-- Inverted tag index: (metric, key, value) -> series_id.
CREATE TABLE IF NOT EXISTS tsdb.series_tag
(
  metric    LowCardinality(String),
  tag_key   LowCardinality(String),
  tag_value String,
  series_id UInt64
)
ENGINE = ReplacingMergeTree
ORDER BY (metric, tag_key, tag_value, series_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS tsdb.series_tag_mv TO tsdb.series_tag AS
SELECT metric, k AS tag_key, v AS tag_value, series_id
FROM tsdb.series
ARRAY JOIN mapKeys(tags) AS k, mapValues(tags) AS v;
