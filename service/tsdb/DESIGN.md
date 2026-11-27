# Design: TSDB service (`service/tsdb`)

## Context

The pollers in this repo already write OpenTSDB line files. `service/snmptk` (`traffic5m`, every 300 s) writes one `.tsdb` file per run, with lines like:

```
in_bw 1795626000000 0.506805440000000 ip=10.177.152.19 intf=73
out_bw 1795626000000 0.050710000000000 ip=10.177.152.19 intf=73
```

(`internal/snmplib/writer.go` `WriteTsdb`, `internal/snmplib2/output.go`.) The metrics are `in_octets`, `out_octets`, `in_rate`, `out_rate`, `in_bw`, `out_bw` and `in_err`, tagged `ip` and `intf` (ifIndex). Timestamps are in milliseconds.

This service stores those points in ClickHouse and serves them back through a REST API. The query API is modelled on OpenTSDB's `/api/query`, so existing dashboards and scripts carry over with little change.

### Goals

1. Ingest OpenTSDB line format over HTTP (`POST /api/ingest`), including out-of-order and re-sent data.
2. Query with OpenTSDB-style parameters (`POST /api/query`): metric, tags, aggregator, downsample with fill policy, explicitTags.
3. Allow any number of metric names and tag keys **without schema changes**.
4. Keep ingest idempotent: posting the same file twice must not double-count.
5. Run on the ClickHouse already in `deployment/infra` (26.8; HTTP `:18123` locally).

### Non-goals (first version)

- OpenTSDB's telnet `put` protocol, `/api/uid`, `/api/annotation`, `/api/tree`.
- Expressions (`/api/query/exp`, `/api/query/gexp`).
- Histograms, and string or annotation values. Values are numbers only.
- Multi-tenant auth. The service sits on the internal network behind a shared API key (see [Security](#security)).

---

## Architecture

```
 snmptk / nokia / other pollers
        │  .tsdb files (OpenTSDB line format)
        ▼
 POST /api/ingest  ──►  tsdb service (Python, FastAPI, N workers)
                          │  parse → validate → series_id → batch
                          ▼
                        ClickHouse  (database `tsdb`)
                          ├─ points      (one row per data point)
                          ├─ series      (one row per metric+tag set)
                          └─ series_tag  (tag index; filled by a materialized view)
                          ▲
 POST /api/query   ──►  tsdb service
                          │  resolve series → downsample/aggregate in SQL → fill/format in Python
                          ▼
                        JSON (OpenTSDB response shape)
```

The service is stateless apart from an in-process cache of known series ids, so it scales horizontally behind a load balancer. ClickHouse does the storage, deduplication and heavy aggregation.

---

## Data model

### Why a series table (and not one column per metric)

The requirement is "many metric names, many tags, no schema change". There are three common designs:

| Option | Shape | Verdict |
|---|---|---|
| Wide table | one column per metric | Rejected: every new metric is an `ALTER TABLE`. |
| Narrow table with tags inline | `(metric, tags Map, ts, value)` per point | Works, but stores the tag map on every point and filters by scanning maps. Tag lookups get slow at billions of rows. |
| **Narrow table + series dictionary** | points carry `series_id`; tags live once in `series` | **Chosen.** This is OpenTSDB's TSUID idea. Points stay small (metric, id, ts, value), and tag filtering touches only the small series index. |

A **series** is one unique combination of metric and tag set, e.g. `in_bw{ip=10.177.152.19, intf=73}`. Its id is a 64-bit hash of the canonical form:

```
series_id = xxh3_64( metric + "\x00" + "k1=v1" + "\x00" + "k2=v2" ... )   # tag keys sorted
```

The service computes this in Python, so ingest never has to look anything up in ClickHouse. With 64 bits, the chance of any collision among 10 M series is about 3 × 10⁻⁶. That is acceptable, and [Ingest](#ingest-pipeline) describes how a collision would be detected.

### Tables

Database `tsdb` (configurable). Timestamps are stored in UTC with millisecond precision.

```sql
-- One row per data point.
CREATE TABLE tsdb.points
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
TTL toDateTime(ts) + INTERVAL 400 DAY DELETE;      -- default retention; per-metric rules: see "Retention per metric"

-- One row per series (metric + tag set). Small: millions of rows, not billions.
CREATE TABLE tsdb.series
(
  metric     LowCardinality(String),
  series_id  UInt64,
  tags       Map(LowCardinality(String), String),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (metric, series_id);

-- Inverted tag index: (metric, key, value) -> series_id. Kept in sync by the MV below.
CREATE TABLE tsdb.series_tag
(
  metric    LowCardinality(String),
  tag_key   LowCardinality(String),
  tag_value String,
  series_id UInt64
)
ENGINE = ReplacingMergeTree
ORDER BY (metric, tag_key, tag_value, series_id);

CREATE MATERIALIZED VIEW tsdb.series_tag_mv TO tsdb.series_tag AS
SELECT metric, k AS tag_key, v AS tag_value, series_id
FROM tsdb.series
ARRAY JOIN mapKeys(tags) AS k, mapValues(tags) AS v;
```

Design notes:

- **Sort key `(metric, series_id, ts)`** keeps each series' points next to each other on disk. A query for one interface over one day reads a few granules, and DoubleDelta and Gorilla compress regular 5-minute series very well. Expect roughly 2–4 bytes per point on disk.
- **Daily partitions** keep late data in its own day's partition and let expired days be removed cleanly (see below).
- **`ReplacingMergeTree(ingested_at)`** gives last-write-wins on `(metric, series_id, ts)`. This is what makes out-of-order and re-sent data safe (next section).
- **`Float64` values.** Integers are exact up to 2⁵³ (about 9 × 10¹⁵). That is fine for rates, bandwidth, errors and per-interval octet deltas. Raw 64-bit octet counters can exceed 2⁵³ on long-uptime high-speed ports, so they should be sent as deltas or rates, which is what snmptk does now. See Open questions.
- **No metric registry table.** A new metric name or tag key just produces new `series` rows. The list of metrics is `SELECT DISTINCT metric FROM tsdb.series`.

### Retention per metric

Retention is set with TTL rules on `tsdb.points`: one default rule plus optional per-metric rules using `DELETE WHERE`. A row is deleted as soon as **any** rule matching it expires. Example:

```sql
ALTER TABLE tsdb.points MODIFY TTL
    toDateTime(ts) + INTERVAL 30  DAY DELETE WHERE metric LIKE 'nokia\_%',     -- shorter than default
    toDateTime(ts) + INTERVAL 90  DAY DELETE WHERE metric IN ('in_err'),
    toDateTime(ts) + INTERVAL 730 DAY DELETE WHERE metric IN ('in_bw', 'out_bw'),  -- longer than default
    toDateTime(ts) + INTERVAL 400 DAY DELETE WHERE metric NOT IN ('in_bw', 'out_bw')  -- default
SETTINGS materialize_ttl_after_modify = 0;
```

Rules and caveats:

- **Shorter than the default:** add a `WHERE` rule. The default rule can stay unconditional.
- **Longer than the default:** the default rule must exclude that metric (`WHERE metric NOT IN (…)`). Otherwise the default deletes the rows first.
- **Metrics with no rule** get the default. A new metric needs no DDL unless it needs a non-default retention.
- **`MODIFY TTL` replaces the whole list**, so always send every rule. The current list is in `SHOW CREATE TABLE tsdb.points`, and the source of truth is a migration file in `sql/`.
- **Changes apply to existing data too.** With `materialize_ttl_after_modify = 0`, the `ALTER` itself is instant and old parts pick up the new rules when they are next merged. To force it, run `ALTER TABLE tsdb.points MATERIALIZE TTL` at a quiet time. This rewrites every part, which is heavy on a large table.
- **Cost:** each daily partition holds every metric, so removing one metric's expired rows means ClickHouse rewrites the part without them, during background merges. Whole parts are dropped without rewriting only when every row in them has expired. That is acceptable with a few retention classes, but expect extra merge I/O around each expiry boundary. If that ever becomes a problem, the fallback is to add the retention class to the partition key, so whole parts expire together.
- **Ingest** rejects points older than the longest retention (`TSDB_MAX_RETENTION_DAYS`). Points between a metric's own retention and that maximum are accepted, and TTL removes them at the next merge.

### Out-of-order and duplicate data

ClickHouse MergeTree does not need rows in time order. Every insert becomes a new part, and background merges sort it. So:

| Case | What happens |
|---|---|
| Points arrive late (minutes or days) | Inserted into their day's partition like any other row. Queries see them immediately. |
| Points within a file are out of order | No effect. Parts are sorted on insert. |
| The same file is re-posted (retry) | Duplicate `(metric, series_id, ts)` rows exist until a merge collapses them. Queries deduplicate explicitly (below), so results are correct before the merge. |
| A corrected value is sent for an existing timestamp | The newest `ingested_at` wins, both in merges and in query dedup. |

Because merges are eventual, queries never rely on them. The point read deduplicates with `argMax(value, ingested_at) … GROUP BY series_id, ts`. For the usual query sizes (a few series × a few thousand points) this costs little. A per-request option `"dedup": false` skips it for very large scans where approximate results are acceptable.

Limits that keep late data sane (all configurable):

- Reject points more than `TSDB_FUTURE_TOLERANCE` (default 10 min) in the future. This usually means a clock or unit bug, such as seconds sent where milliseconds were expected.
- Reject points older than the longest retention period (`TSDB_MAX_RETENTION_DAYS`). The TTL would drop them anyway.
- One insert may touch at most `max_partitions_per_insert_block` (default 100) partitions, i.e. 100 days. The writer splits batches by day, so even a back-fill of a year of data works.

---

## Ingest pipeline

### `POST /api/ingest`

Request body: OpenTSDB line format, one point per line.

```
<metric> <timestamp> <value> <tagk1=tagv1> [<tagk2=tagv2> ...]
```

- **Body forms:** raw body (`Content-Type: text/plain`, `--data-binary @file.tsdb`), or `multipart/form-data` with a `file` field. Either may be gzip, detected by its magic bytes (so `Content-Encoding: gzip`, a `.gz` upload and concatenated gzip files all work).
- **Timestamp:** seconds (10 digits) or milliseconds (13 digits), as in OpenTSDB. Values above `9_999_999_999` are milliseconds.
- **Value:** an integer or float literal. `NaN` and `±Inf` are rejected.
- **Tags:** at least 1, at most `TSDB_MAX_TAGS` (default 8, the OpenTSDB default). Keys must be unique within a line. Allowed characters in names and values are OpenTSDB's set `[A-Za-z0-9-_./]`, plus Unicode letters. Anything else is rejected rather than escaped.
- Blank lines and lines starting with `#` are skipped.

Examples:

```bash
curl -sS -X POST http://tsdb:8080/api/ingest \
  -H 'Content-Type: text/plain' -H 'X-API-Key: …' \
  --data-binary @traffic5m-host-20261126T1005.tsdb

curl -sS -X POST http://tsdb:8080/api/ingest -H 'X-API-Key: …' \
  -F file=@traffic5m-host-20261126T1005.tsdb.gz
```

Response (shape follows OpenTSDB `/api/put?summary&details`):

```json
{ "success": 1843200, "failed": 2,
  "errors": [ { "line": 5121, "error": "value is not a number", "text": "in_bw 1795626000000 abc ip=…" } ] }
```

- `200` if every line was stored. `400` if any line failed, while still storing the valid lines. A client retry of the whole file is harmless because of dedup.
- `errors` lists the first 100 failures. `?details=false` returns only the counts.
- `413` if the body exceeds `TSDB_MAX_BODY` (default 512 MB uncompressed). `503` if ClickHouse is unreachable, in which case nothing from the failed batch is acknowledged.

### Processing

```
stream body (chunked, gunzip on the fly)
  └─ parse line → validate → canonical tags → series_id
       └─ append to column buffers  (metric[], series_id[], ts[], value[])
            └─ every 200k rows or end of body:
                 1. insert unseen series rows into tsdb.series   (cache miss only)
                 2. insert points (columnar) into tsdb.points
```

- **Streaming:** the body is never held in memory whole. Memory per request is bounded by the batch size, about 200k rows ≈ 10 MB.
- **Series cache:** each worker keeps a bounded LRU set of `series_id`s it has already registered (default 2 M ids ≈ 150 MB). On a miss it inserts the `series` row. Inserting a known series again is harmless (ReplacingMergeTree), so the cache is only an optimization and needs no warm-up or coordination between workers. Once a day the cache is cleared so `updated_at` is refreshed, which lets `/api/suggest` hide series that have not been seen for a long time.
- **Collision check (cheap):** on a cache miss the service also keeps the canonical string. If two different strings map to the same id in one process, it logs an error and rejects the line. A cross-process check is not worth the cost at a 10⁻⁶ probability.
- **Insert path:** `clickhouse-connect` over HTTP with columnar inserts. The service does its own batching (large inserts, few parts), so ClickHouse `async_insert` is not needed. Server-side `async_insert=1, wait_for_async_insert=1` is still a reasonable switch for many small clients.
- **Order of writes:** series rows first, then points, so a point is never queryable without its series.
- **Acknowledgement:** the HTTP response is sent only after every batch's insert has returned. An acknowledged point is durable in ClickHouse.

### Throughput estimate

`intf` holds about 2.8 M interfaces. If, say, 1 M of them are polled every 5 minutes with 7 metrics each:

| | |
|---|---|
| Points per 5-min cycle | 7 M |
| Points per day | about 2 B |
| Disk per day (≈3 B/point) | about 6 GB |
| Required ingest rate | 7 M lines in well under 5 min. Measured on the dev machine: parsing about 800k lines/s, end to end (parse + ClickHouse insert) about 250–300k lines/s per worker, so one cycle takes about 25–30 s on one worker. |

The parser caches validated tag strings and metric names per request, because pollers repeat the same `ip=… intf=…` for every metric of an interface (2.7× faster than parsing every line from scratch). If ingest becomes the bottleneck, the first step is more workers. The second is a vectorized parser (pyarrow CSV reader with space delimiter plus a tag split), which is still Python and needs no API change.

---

## Query API

### `POST /api/query`

Request (OpenTSDB-compatible subset):

```json
{
  "start": 1764090000,
  "end":   1764176400,
  "queries": [
    { "metric": "in_octets", "aggregator": "sum", "downsample": "5m-sum-nan",
      "tags": { "ip": "10.163.193.127", "intf": "2" }, "explicitTags": true },
    { "metric": "in_rate",   "aggregator": "sum", "downsample": "5m-avg-nan",
      "tags": { "ip": "10.163.193.127", "intf": "2" }, "explicitTags": true }
  ]
}
```

| Field | Meaning |
|---|---|
| `start` (required) | Seconds or ms epoch, or relative `"1h-ago"`, `"7d-ago"`. Units are `ms s m h d w n y`, as in OpenTSDB. |
| `end` | Same formats. Default is now. **Inclusive**, as in OpenTSDB. |
| `queries[]` | One sub-query per entry, run concurrently. Results are returned in request order. |
| `metric` (required) | Metric name. |
| `aggregator` (required) | How series in one group are combined: `sum`, `avg`, `min`, `max`, `count`, `dev`, `zimsum`, `mimmin`, `mimmax`, `none`. `none` returns every series separately. |
| `downsample` | `<interval>-<function>[-<fill>]`. Intervals look like `30s`, `5m`, `1h`, `1d`, or `0all` (one bucket for the whole range). Functions are `avg`, `sum`, `min`, `max`, `count`, `first`, `last`, `dev`, `p50`, `p90`, `p95`, `p99`. Fill is `none` (default), `nan`, `null` or `zero`. |
| `tags` | Tag filters. `v` matches exactly. `v1\|v2` is literal-or and groups by the key. `*` is a wildcard: the key must exist, and results are grouped by it. |
| `filters` | The OpenTSDB 2.2+ filter form, e.g. `[{ "type":"literal_or", "tagk":"intf", "filter":"1\|2", "groupBy":true }]`. The supported types are `literal_or`, `wildcard`, `regexp` and `not_literal_or`. `tags` is converted internally into this form. |
| `explicitTags` | If `true`, a series matches only when its tag keys are **exactly** the queried keys, with no extras. |
| `rate`, `rateOptions` | Phase 2 (see [Roadmap](#roadmap)). They are rejected with 400 until then, never silently ignored. |
| top level `msResolution` | If `true`, `dps` keys are in ms. Otherwise they are in seconds. |
| top level `arrays` | If `true`, `dps` is `[[ts, value], …]` instead of an object. |
| top level `showQuery` | Echo the parsed sub-query in each result, with `index` = its position in `queries` (as OpenTSDB). |

Response, one element per output group (OpenTSDB shape):

```json
[
  {
    "metric": "in_octets",
    "tags": { "ip": "10.163.193.127", "intf": "2" },
    "aggregateTags": [],
    "dps": { "1764090000": 81234567.0, "1764090300": 80119022.0, "1764090600": null }
  },
  { "metric": "in_rate", "tags": { "ip": "10.163.193.127", "intf": "2" }, "aggregateTags": [], "dps": { … } }
]
```

- `tags` holds keys whose value is the same for every series in the group. `aggregateTags` lists the keys that were aggregated away.
- A sub-query that matches no series contributes no element. OpenTSDB returns 400 for an unknown metric. Here it is a normal empty result, which is friendlier for dashboards that ask for many metrics. This is one of the documented deviations below.
- `nan` and `null` fill both serialize as JSON `null`, because JSON has no NaN.

### Execution of one sub-query

**Step 1: resolve series** through the tag index. For the example `ip=10.163.193.127, intf=2, explicitTags=true`:

```sql
SELECT series_id, any(tags) AS series_tags   -- not "AS tags": the alias would shadow the column in WHERE
FROM tsdb.series
WHERE metric = {metric:String}
  AND series_id IN (
    SELECT series_id FROM tsdb.series_tag
    WHERE metric = {metric:String}
      AND ( (tag_key = 'ip'   AND tag_value = '10.163.193.127')
         OR (tag_key = 'intf' AND tag_value = '2') )
    GROUP BY series_id
    HAVING uniqExact(tag_key) = 2            -- every filter key matched
  )
  AND length(tags) = 2                       -- explicitTags only
GROUP BY series_id
LIMIT {max_series + 1}
```

Filter translations:

| Filter | Condition on `series_tag` |
|---|---|
| exact `k=v` | `tag_key='k' AND tag_value='v'` |
| literal_or `v1\|v2` | `tag_key='k' AND tag_value IN ('v1','v2')` |
| wildcard `*` | `tag_key='k'` (only the key must exist) |
| wildcard `abc*` | `tag_key='k' AND tag_value LIKE 'abc%'` |
| regexp | `tag_key='k' AND match(tag_value, '…')` |
| not_literal_or `v1\|v2` | `tag_key='k'` (key must exist), then `NOT has(['v1','v2'], tags['k'])` on `series` |

**explicitTags.** Let *K* be the set of distinct tag keys named in `tags`/`filters`, |K| = N.

- The `HAVING uniqExact(tag_key) = N` clause always applies. It means every queried key is present and its filter matched.
- With `explicitTags: true`, the clause `length(tags) = N` is added. Together the two mean the series' key set **equals** K: no missing keys and no extra keys. The check runs on the small `series` table, not on points.
- With `explicitTags: false` (the default), series with extra keys also match. They are aggregated together with the rest, and the extra keys show up in `aggregateTags`. Example: `in_bw{ip=…, intf=2}` and `in_bw{ip=…, intf=2, vlan=10}` would be summed. With `explicitTags: true`, only the first matches.
- A `not_literal_or` key counts towards N too. Its series_tag condition is just `tag_key='k'` (the key must exist), and the value exclusion is applied afterwards. So `explicitTags` treats it like any other queried key.
- `explicitTags: true` with no tags at all matches only series that have no tags. Ingest requires at least one tag, so that is always empty. The API returns 400 for this combination rather than a silent empty result.

With no tag filters, every series of the metric is selected. If the number of series exceeds `TSDB_MAX_SERIES_PER_QUERY` (default 20 000), the API returns 400 with the count, and does not run a huge scan.

Every value goes in as a bound query parameter (`{name:Type}`), never by string concatenation.

**Step 2: read, dedup, downsample, aggregate (one SQL statement).** Downsampling happens per series first, then aggregation across series per group and bucket, which is the same order OpenTSDB uses:

```sql
SELECT
  grp,                                                     -- group key (values of group-by tags)
  bucket,
  sum(ds) AS val                                           -- <- aggregator
FROM (
  SELECT
    series_id,
    transform(series_id, {ids:Array(UInt64)}, {grps:Array(String)}, '') AS grp,
    intDiv(toUnixTimestamp64Milli(ts), {iv_ms:Int64}) * {iv_ms:Int64} AS bucket,   -- epoch-aligned, in ms
    avg(v) AS ds                                           -- <- downsample function
  FROM (
    SELECT series_id, ts, argMax(value, ingested_at) AS v  -- dedup (out-of-order / retries)
    FROM tsdb.points
    WHERE metric = {metric:String}
      AND series_id IN {ids:Array(UInt64)}
      AND ts >= fromUnixTimestamp64Milli({start_ms:Int64})
      AND ts <= fromUnixTimestamp64Milli({end_ms:Int64})
    GROUP BY series_id, ts
  )
  GROUP BY series_id, grp, bucket
)
GROUP BY grp, bucket
ORDER BY grp, bucket
```

- The group key per series is computed in Python from the resolved tags (step 1). The implementation sends the `(series_id, group)` pairs as an external table `_sel` (TSV), not as bound arrays, because ClickHouse caps an HTTP form field at 128 KB (`http_max_field_value_size`, from the server profile), which is only a few thousand ids. The query filters with `series_id IN (SELECT series_id FROM _sel)` and joins `_sel` for the group, so ClickHouse never re-reads tags. The SQL above shows the logic with arrays for readability.
- Function mapping: `avg`, `sum`, `min`, `max`, `count`. `first` is `argMin(v, ts)`, `last` is `argMax(v, ts)`, `dev` is `stddevPop`, and `pNN` is `quantile(0.NN)`.
- **Aggregation in SQL vs Python.** For `sum/avg/min/max/count/dev` with fill `none/nan/null`, missing buckets are simply absent, which matches OpenTSDB's skip-NaN behaviour. In that case the whole query is aggregated in ClickHouse and only one row per group and bucket crosses the wire, even for `ip=*` queries over thousands of series. With fill `zero`, `zimsum`/`mimmin`/`mimmax`, or `aggregator: none`, step 2 stops after the per-series level and Python does the cross-series step. Those cases are capped by the series limit.
- **No downsample:** raw (deduplicated) points are aggregated by exact timestamp. OpenTSDB instead linearly interpolates between series whose timestamps don't line up. That is a deliberate deviation, because pollers here share a 5-minute grid. Clients that mix grids should downsample.
- Buckets are aligned to the epoch (`intDiv(ts_ms, interval_ms) * interval_ms`), so `5m` buckets start at :00, :05, and so on, as in OpenTSDB. `0all` becomes one bucket stamped at `start`.

**Step 3: fill and format (Python).** For fill `nan`, `null` or `zero`, generate every bucket from `align(start)` to `end` and insert `null` or `0` where a bucket is missing. Then build `dps`, `tags` and `aggregateTags`.

**Concurrency and limits.** Sub-queries run concurrently (`asyncio.gather`, bounded by `TSDB_QUERY_CONCURRENCY`, default 8). Each statement runs with ClickHouse `max_execution_time` (default 30 s) and `max_result_rows`. A query whose output would exceed `TSDB_MAX_POINTS` (default 5 M) returns 400 asking for a coarser downsample.

### Deviations from OpenTSDB (summary)

| Behaviour | OpenTSDB | This service |
|---|---|---|
| Unknown metric | 400 error | empty result for that sub-query |
| Cross-series alignment without downsample | linear interpolation | exact-timestamp aggregation |
| NaN in output | literal `NaN` (invalid JSON) | `null` |
| `rate` | supported | Phase 2. Rejected with 400 until then. |
| Tag value charset | strict | strict plus Unicode letters |

### `GET /api/query` (OpenTSDB URL syntax)

```
GET /api/query?start=1d-ago&end=now&m=avg:1h-max-nan:explicit_tags:in_bw{ip=10.163.193.127,intf=2}
```

- `m=<aggregator>:[rate:][<downsample>:][explicit_tags:]<metric>[{<group-by filters>}][{<non-group-by filters>}]`, repeatable for several sub-queries.
- A filter is `tagk=value` (same rules as the JSON `tags` map) or `tagk=type(value)`: `literal_or(1|2)`, `wildcard(ab*)`, `regexp(^10\.)`, `not_literal_or(…)`. Commas and colons inside parentheses are safe.
- Also `ms`, `arrays`, `show_query` and `dedup` as URL flags. The result is identical to the equivalent POST.

### Other endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/suggest?type=metrics\|tagk\|tagv&q=prefix&max=25` | Prefix autocomplete from `series` and `series_tag`; returns a list of strings like OpenTSDB. Extension: `metric=` (and `tagk=` for tagv) narrow the result. |
| `GET /api/stats` | Overview for the Metrics page in the frontend: points, disk size and compression (from `system.parts`), data days, and per metric: series, tag keys, points in the last 24 h, newest point, last ingest. Cached 30 s. |
| `GET /api/health` | Liveness, plus a ping to ClickHouse. 503 when ClickHouse is unreachable. |
| `GET /metrics` | Phase 2. Prometheus metrics for the service itself: lines ingested and failed, insert latency, query latency, series cache hit rate. |

---

## Postgres backend

`TSDB_BACKEND=postgres` stores the same data in plain Postgres (16+, developed on 18, no extensions). It is for installs that should not run ClickHouse. The API, validation, series ids and responses are identical; only `src/tsdb/store/postgres.py`, `store/pg_sql.py` and `sql/postgres/` differ. The ingest pipeline and query engine talk to a small `Store` interface (`store/__init__.py`: `write`, `resolve`, `points`, `suggest`, `stats`, `migrate`), with one implementation per backend.

### Schema (`sql/postgres/001_schema.sql`, in schema `PG_SCHEMA`)

| Table | Shape | Notes |
|---|---|---|
| `series` | `series_id bigint PK, metric, tags jsonb, n_tags, updated_at` | The xxh3 id is stored as signed bigint (same 64 bits). `n_tags` serves `explicitTags`. |
| `series_tag` | PK `(metric, tag_key, tag_value, series_id)` | Same inverted index as ClickHouse, written in the same transaction as `series`. |
| `points` | `series_id, ts timestamptz, value float8, ingested_at`, PK `(series_id, ts)` | `PARTITION BY RANGE (ts)`, one partition per UTC day (`points_YYYYMMDD`). |
| `retention` | `metric_like, days` | Optional per-metric rules shorter than `TSDB_MAX_RETENTION_DAYS`. |

Text columns use `COLLATE "C"`, so prefix `LIKE` (suggest) can use the indexes and ordering matches ClickHouse.

### Differences from the ClickHouse design

- **Dedup on write, not on read.** The primary key makes `(series_id, ts)` unique. A batch is `COPY`ed (binary) into a per-connection temp table, collapsed with `DISTINCT ON` (the last line of the body wins) and upserted with `ON CONFLICT DO UPDATE ... WHERE value IS DISTINCT FROM`, so a re-sent file rewrites nothing. Queries therefore need no `argMax` step, and `"dedup": false` has no effect.
- **Partitions are created on demand.** Before a write, the worker creates any missing daily partitions under an advisory lock, so concurrent workers never race on DDL. If a partition vanished, the write is retried once after re-creating it.
- **Retention is a maintenance loop, not TTL.** Each worker runs it every `PG_MAINTENANCE_INTERVAL_S` (default 1 h). An advisory lock lets only one worker do the work. It pre-creates partitions for the next days, drops partitions that lie entirely before `TSDB_MAX_RETENTION_DAYS` (a cheap `DROP TABLE`), and deletes older points of metrics that match a `retention` rule (row deletes: slower, so keep few rules). Metrics without a rule are kept for `TSDB_MAX_RETENTION_DAYS`. `tsdb-migrate` runs one pass at the end.
- **Same SQL plan shape.** Step 1 is the same `series_tag` lookup with `HAVING count(DISTINCT tag_key) = N`. Step 2 downsamples per series and then aggregates per group in SQL. Groups are joined in with `unnest(ids, groups)` in place of `transform()`. Percentiles use `percentile_cont`, which is exact, whereas ClickHouse `quantile` is approximate, so `pNN` can differ slightly between backends. Regexps are Postgres ARE syntax, not RE2.
- **Stats are estimates.** `rows` comes from `pg_stat_user_tables.n_live_tup`, and `uncompressed_bytes` equals `disk_bytes`, because heap rows are not compressed.

### Sizing

On a 20 M-point test (`BENCHMARK.md`), Postgres stored 103 bytes per point (heap tuple plus primary-key index), against 5 on ClickHouse. It ingested 60k lines/s per worker, against 149k. Single-series and per-device queries were faster on Postgres; metric-wide scans over 10k series were 10–17× slower. As a rule of thumb, it suits up to some tens of millions of points per day. The full `traffic5m` scale (about 2 B points per day) belongs on ClickHouse.

---

## Implementation

### Stack

- Python 3.12+ (developed on 3.14), managed with `uv` like the other Python services (`service/nokia`, `service/pgadm`).
- FastAPI + uvicorn, run with `--workers N`.
- `clickhouse-connect[async]` (HTTP, aiohttp-based async client) for both ingest and query. Session ids are off so sub-queries can run concurrently, and parameters are form-encoded in the body so large series-id arrays don't hit URL limits.
- `pydantic` v2 for request models, `xxhash` for series ids, `orjson` for responses.

### Layout

```
service/tsdb/
├── DESIGN.md
├── README.md
├── pyproject.toml
├── .env.example
├── sql/
│   ├── 001_schema.sql          # the DDL above
│   └── 002_retention.sql       # per-metric TTL rules (template)
├── src/tsdb/
│   ├── main.py                 # FastAPI app, lifespan (ClickHouse client)
│   ├── config.py               # env settings (pydantic-settings)
│   ├── ch.py                   # async ClickHouse client
│   ├── store/                  # storage backends behind one interface (TSDB_BACKEND)
│   │   ├── __init__.py         # Store interface, open/close/get
│   │   ├── clickhouse.py       # ClickHouse: SQL from query/resolve.py and query/plan.py
│   │   ├── postgres.py         # Postgres: partitions, COPY + upsert, maintenance loop
│   │   └── pg_sql.py           # Postgres versions of the step 1 / step 2 SQL
│   ├── migrate.py              # `uv run tsdb-migrate [--database NAME]`: applies sql/*.sql
│   ├── ingest/
│   │   ├── parser.py           # line → Point + validation (caching LineParser)
│   │   ├── series.py           # xxh3 series id, per-worker series cache
│   │   ├── writer.py           # columnar batch, split by day, series-then-points inserts
│   │   └── pipeline.py         # streaming body, gzip detection, line splitting, batching
│   ├── query/
│   │   ├── models.py           # pydantic request models
│   │   ├── parse.py            # time ("1h-ago"), downsample spec, aggregators, tag filters
│   │   ├── url.py              # GET m= syntax → sub-query
│   │   ├── resolve.py          # step 1: series lookup SQL
│   │   ├── plan.py             # step 2: points SQL (SQL vs Python aggregation)
│   │   ├── assemble.py         # step 3: groups, Python aggregation, fill, dps formatting
│   │   └── run.py              # validate all sub-queries, run them concurrently
│   └── api/
│       └── routes.py           # POST/GET /api/query, POST /api/ingest, GET /api/health
└── tests/
    ├── test_parser.py          # line format edge cases, batching, collisions
    ├── test_query_parse.py     # time/downsample/filter parsing, generated SQL, fill, GET syntax
    └── test_e2e.py             # app against ClickHouse in a throwaway tsdb_test database
```

### Configuration (environment)

| Variable | Default | |
|---|---|---|
| `TSDB_BACKEND` | `clickhouse` | `clickhouse` or `postgres` |
| `CH_URL` | `http://localhost:18123` | ClickHouse HTTP endpoint (local dev compose) |
| `CH_USER`, `CH_PASSWORD` | — | |
| `CH_DATABASE` | `tsdb` | |
| `PG_URL` | `postgresql://localhost:15432/pmsonline` | Postgres database (local dev compose) |
| `PG_USER`, `PG_PASSWORD` | — | |
| `PG_SCHEMA` | `tsdb` | schema that holds the tables |
| `PG_POOL_SIZE` | `10` | connections per worker |
| `PG_MAINTENANCE_INTERVAL_S` | `3600` | partition upkeep and retention; `0` disables |
| `TSDB_API_KEY` | — | required header `X-API-Key`. Empty disables the check (dev only). |
| `TSDB_MAX_RETENTION_DAYS` | `400` | longest TTL of any metric; older points are rejected at ingest. Retention itself is the TTL rules in ClickHouse. |
| `TSDB_FUTURE_TOLERANCE` | `10m` | |
| `TSDB_MAX_TAGS` | `8` | |
| `TSDB_MAX_BODY` | `512MB` | uncompressed |
| `TSDB_BATCH_ROWS` | `200000` | |
| `TSDB_SERIES_CACHE` | `2000000` | per worker |
| `TSDB_MAX_SERIES_PER_QUERY` | `20000` | |
| `TSDB_MAX_POINTS` | `5000000` | per query response |
| `TSDB_QUERY_CONCURRENCY` | `8` | sub-queries in flight per request |

### Security

- Shared API key on every endpoint except `/api/health`. Ingest and query can use separate keys if needed.
- All SQL values are bound parameters. Metric names and tag keys are validated against the charset before use, and identifiers are never interpolated.
- The ClickHouse user for the service has `INSERT, SELECT` on `tsdb.*` only. DDL runs from the migrate command with a separate admin user.

---

## Testing

- **Unit:** parser (seconds vs ms, negative and float values, bad tags, duplicate keys, too many tags), downsample spec parsing, relative time parsing, filter-to-SQL translation, fill generation.
- **End-to-end** against the dev ClickHouse:
  1. Ingest a file, query it back, and compare with hand-computed 5-minute sums and averages.
  2. Ingest the same file again and check the results are unchanged (idempotent).
  3. Ingest a shuffled file plus a late file for yesterday, and check the results are identical to in-order ingest.
  4. Send a corrected value for one timestamp and check the latest value wins.
  5. Query with `explicitTags` against series that carry an extra tag key, and check they are excluded.
  6. Query `intf=*` with `aggregator: sum` and `aggregator: none`, and check grouping and `aggregateTags`.
- **Load:** replay one real `traffic5m` cycle (millions of lines) and measure lines/s per worker and parts created per insert.

---

## Roadmap

| Phase | Scope |
|---|---|
| **1** | Schema and migrate command. `POST /api/ingest`. `POST /api/query` with tags/filters, explicitTags, aggregators, downsample and fill. `/api/health`. Tests above. |
| **2** | `rate` / `rateOptions` (`counter`, `counterMax`, `resetValue`, `dropResets`), computed per series after dedup with window functions (`lagInFrame`) before downsampling. `/metrics`. (`/api/suggest` and `/api/stats` are done.) |
| **3** | Rollup tables (`points_1h`, `points_1d`, `AggregatingMergeTree` with sum/count/min/max states), filled by a scheduled job over closed days rather than a materialized view, so late data and duplicates are folded in correctly. The query planner uses a rollup when the downsample interval is a multiple of it. Longer retention on rollups than on raw points. |
| **4** | HA: `ReplicatedMergeTree` on a ClickHouse cluster (Keeper), and a k8s deployment next to `deployment/infra`. |

---

## Open questions

1. **Retention:** what is the default for raw 5-minute points (400 days is a placeholder), and which metrics need their own TTL rule? At about 6 GB/day, a year is about 2.2 TB before rollups.
2. **Scale:** how many series will actually be sent (all 2.8 M interfaces or a subset), and which other pollers (nokia PM data, uptime) will send to this service? This sets worker count and cache size.
3. **Counters:** will anyone send raw 64-bit counters? If so, values above 2⁵³ lose precision in `Float64`. Options are an extra `Int64`/`UInt64` column for integer metrics, or requiring deltas or rates (the current snmptk behaviour).
4. **Unknown metric behaviour:** keep "empty result", or match OpenTSDB's 400 for strict compatibility with existing clients?
5. **Shipping:** do pollers POST files directly after each run, or does a small shipper watch the `.tsdb` output directories and retry on failure? The second survives service downtime without changing the pollers.
