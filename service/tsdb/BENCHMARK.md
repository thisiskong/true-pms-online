# Benchmark: ClickHouse vs Postgres backend

Run 2026-11-27 with `bench/backends.py`. Raw numbers are in `bench/results-2026-11-27.json`.

## Setup

| | |
|---|---|
| Dataset | 250 devices × 40 interfaces × 7 metrics (`in_octets` … `in_err`), 5-minute points for one UTC day (288 cycles) = **20.16 M points, 70 000 series**. Deterministic and identical for both backends. |
| Ingest path | The real pipeline (`ingest_stream`: parse, series ids, batches of 200 k), one stream, **one worker process**. |
| Query path | `run_query`, the same code that serves `POST /api/query`. Each query runs once (first), then 15 times (median / p95). |
| Machine | Dev laptop, Windows 11, 14 cores, 15 GB RAM. The service runs on the host; the databases run in Docker from `deployment/infra`. |
| ClickHouse | 26.8.36.3, default settings. Sizes were measured after `OPTIMIZE TABLE … FINAL`. |
| Postgres | 18.6, **default settings** (`shared_buffers` 128 MB, `work_mem` 4 MB, 2 parallel workers). `VACUUM ANALYZE` ran after ingest. |

## Ingest and storage

| | ClickHouse | Postgres | Ratio |
|---|---:|---:|---:|
| Ingest, 20.16 M lines | 135 s | 339 s | |
| **Lines per second (1 worker)** | **149 k** | **60 k** | CH 2.5× faster |
| Re-send one cycle (70 k existing points) | 1.7 s | 3.2 s | |
| Points table on disk | 101 MB | 2 072 MB (1 214 MB heap + PK index) | |
| **Bytes per point** | **5.0** | **102.8** | PG 21× larger |
| All tables | 105 MB | 2 110 MB | |

ClickHouse compresses 665 MB of raw columns to 101 MB (6.6×). Postgres stores each point as a roughly 56-byte heap tuple plus a primary-key index entry.

## Queries (one day, `in_bw`)

Times in ms. Lower is better. ClickHouse has a floor of about 35 ms per query here, because each sub-query is two HTTP round trips (resolve, then points). Postgres uses pooled binary connections.

| Query | Result | CH median | CH p95 | PG median | PG p95 | Faster |
|---|---|---:|---:|---:|---:|---|
| 1 series, raw | 288 pts | 37 | 48 | **8** | 9 | PG 4.7× |
| 1 series, `1h-avg` | 24 pts | 39 | 41 | **9** | 11 | PG 4.5× |
| 1 device, 40 series grouped, `5m-sum` | 40 × 288 | 73 | 79 | **57** | 67 | PG 1.3× |
| 1 device total (40 summed), `1h-sum` | 24 pts | 51 | 55 | **24** | 27 | PG 2.1× |
| 1 device, `1h-p95` per intf | 40 × 24 | 57 | 62 | **36** | 39 | PG 1.6× |
| 1 device, `5m-avg-zero` (Python aggregation) | 40 × 288 | 78 | 83 | **61** | 75 | PG 1.3× |
| 10 devices via regexp filter, `1h-max` | 10 × 24 | **89** | 97 | 355 | 378 | CH 4.0× |
| Whole metric total (10 000 series), `1h-sum` | 24 pts | **281** | 321 | 3 864 | 3 904 | CH 13.7× |
| Whole metric, every series (`none`), `1d-avg` | 10 000 × 1 | **363** | 392 | 3 827 | 3 960 | CH 10.5× |
| Whole metric total, raw 5 m | 288 pts | **261** | 291 | 4 533 | 4 636 | CH 17.4× |
| 32 single-series queries at once (wall) | | **378** | | 2 173 | | CH 5.7× |
| `/api/suggest` tagv | 25 values | 11 | | **5** | | PG 2.3× |

The 32-at-once Postgres figure was measured once, at the start of a burst. It probably includes opening up to 9 new pool connections (`min_size` is 1). Treat it as an upper bound.

**Same answers.** Every query returned the same groups, keys and number of points on both backends. Values match to 3 decimals everywhere. Where they differ beyond that, it is floating-point summation order: sums over 10 000 series with values around 10⁷. `p95` matched too, although ClickHouse's `quantile` is approximate in general and Postgres's `percentile_cont` is exact.

## Reading the results

- **Small dashboard queries (one series or one device) are faster on Postgres**, because it has no per-query HTTP overhead and finds the points through the primary-key index. Both backends answer these in well under 100 ms, so users won't notice the difference.
- **Wide scans are 10–17× slower on Postgres.** That covers a whole metric, many devices, or a regexp over the tag index. Postgres reads row by row from about 100-byte tuples, while ClickHouse reads a few compressed columns in parallel. This gap grows with the data. At 10× the series count, Postgres would need around 40 s for a whole-metric query and hit the 30 s query timeout.
- **Postgres ingest is about 2.5× slower per worker and storage is about 21× larger.** At the full `traffic5m` scale in DESIGN.md (about 2 B points per day), Postgres would need about 200 GB of disk per day, against about 10 GB on ClickHouse. Ingest itself keeps up on either backend: one 7 M-point cycle takes about 2 min on one Postgres worker, against about 47 s on ClickHouse. Storage and wide queries are the limits.

## Recommendation

| Use case | Backend |
|---|---|
| Full-scale traffic5m (about 1 M interfaces, billions of points per day), metric-wide dashboards | **ClickHouse** |
| Small or medium installs: up to roughly 10–50 M points per day and tens of thousands of series per metric, mostly per-device dashboards, where running ClickHouse is not wanted | **Postgres** |

Easy wins for Postgres before reaching for ClickHouse: raise `shared_buffers` (25 % of RAM) and `work_mem` (for example 64 MB), which this run left at their defaults; set `PG_POOL_SIZE` to the expected concurrency; and add downsampled rollup tables (Roadmap phase 3) for metric-wide views.

## Found along the way

The ClickHouse backend could not serve a query matching more than a few thousand series. The series ids were sent as one HTTP form field, which ClickHouse caps at 128 KB (`http_max_field_value_size`, read from the server profile, so it cannot be raised per query). The ids now go as an external table `_sel` (`query/plan.py`), and `test_many_series_in_one_query` covers it on both backends.
