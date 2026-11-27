"""End-to-end: the real app against each storage backend, in a throwaway database/schema `tsdb_test`.

ClickHouse needs CH_URL / CH_USER / CH_PASSWORD, Postgres PG_URL / PG_USER / PG_PASSWORD in the
environment. Every test runs once per backend; a backend that is unreachable is skipped.
"""
import asyncio
import gzip
import os
import random
import time

import pytest

TEST_DB = "tsdb_test"
os.environ["CH_DATABASE"] = TEST_DB
os.environ["PG_SCHEMA"] = TEST_DB

from tsdb import ch, config, migrate  # noqa: E402

DAY_MS = 86_400_000
# Two days ago, on a 1-hour boundary: inside retention, never in the future.
BASE_S = (int(time.time()) - 2 * 86400) // 3600 * 3600
IP = "10.163.193.127"


async def _drop(backend: str) -> None:
  s = config.get_settings()
  if backend == "clickhouse":
    c = await ch.open_client(s.model_copy(update={"ch_database": "default"}))
    try:
      await c.command(f"DROP DATABASE IF EXISTS {TEST_DB}")
    finally:
      await ch.close_client()
  else:
    import asyncpg
    conn = await asyncpg.connect(s.pg_url, user=s.pg_user, password=s.pg_password or None, timeout=5)
    try:
      await conn.execute(f"DROP SCHEMA IF EXISTS {TEST_DB} CASCADE")
    finally:
      await conn.close()


@pytest.fixture(scope="module", params=["clickhouse", "postgres"])
def backend(request):
  os.environ["TSDB_BACKEND"] = request.param
  config.get_settings.cache_clear()
  try:
    asyncio.run(_drop(request.param))
  except Exception as e:
    pytest.skip(f"{request.param} not reachable: {e}")
  yield request.param
  asyncio.run(_drop(request.param))
  os.environ.pop("TSDB_BACKEND", None)
  config.get_settings.cache_clear()


@pytest.fixture(scope="module")
def api(backend):
  asyncio.run(migrate.migrate(TEST_DB))
  from fastapi.testclient import TestClient
  from tsdb.api import meta
  from tsdb.api.routes import series_cache
  from tsdb.main import app
  meta._stats_cache.clear()
  series_cache(config.get_settings())._ids.clear()   # ids registered with the other backend's run
  with TestClient(app) as client:
    yield client


def lines(metric: str, intf: str, values: list[float], extra: str = "", step_s: int = 60) -> list[str]:
  return [f"{metric} {(BASE_S + i * step_s) * 1000} {v} ip={IP} intf={intf}{extra}" for i, v in enumerate(values)]


def ingest(api, body: str, **kw):
  return api.post("/api/ingest", content=body.encode(), headers={"Content-Type": "text/plain"}, **kw)


def query(api, *subs, start=BASE_S, end=BASE_S + 3599, **top):
  return api.post("/api/query", json={"start": start, "end": end, "queries": list(subs), **top})


def sub(metric, aggregator="sum", downsample="5m-sum-nan", explicit=True, **tags):
  return {"metric": metric, "aggregator": aggregator, "downsample": downsample,
          "tags": tags or {"ip": IP, "intf": "2"}, "explicitTags": explicit}


# 60 one-minute points: value = minute index. 5-minute sums: 0+1+2+3+4=10, 35, 60, ...
VALUES = [float(i) for i in range(60)]
SUMS_5M = {str(BASE_S + b * 300): float(sum(range(b * 5, b * 5 + 5))) for b in range(12)}


@pytest.fixture(scope="module")
def loaded(api):
  body = "\n".join(
    lines("in_bw", "2", VALUES)
    + lines("in_bw", "3", [100.0] * 60)
    + lines("in_bw", "2", [1000.0] * 60, extra=" vlan=10")   # same ip/intf plus an extra key
    + ["# comment", ""]
  )
  r = ingest(api, body)
  assert r.status_code == 200, r.text
  assert r.json() == {"success": 180, "failed": 0, "errors": []}
  return api


def test_health(api, backend):
  r = api.get("/api/health")
  j = r.json()
  assert r.status_code == 200 and j["backend"] == backend and j["storage"] is True and j[backend] is True


def test_query_5m_sum_explicit(loaded):
  r = query(loaded, sub("in_bw"))
  assert r.status_code == 200, r.text
  [res] = r.json()
  assert res["metric"] == "in_bw" and res["tags"] == {"ip": IP, "intf": "2"} and res["aggregateTags"] == []
  assert res["dps"] == SUMS_5M


def test_reingest_is_idempotent(loaded):
  assert ingest(loaded, "\n".join(lines("in_bw", "2", VALUES))).status_code == 200
  assert query(loaded, sub("in_bw")).json()[0]["dps"] == SUMS_5M


def test_out_of_order_and_late_data_match_in_order(loaded):
  ordered = lines("ooo_a", "2", VALUES)
  shuffled = lines("ooo_b", "2", VALUES)
  random.Random(1).shuffle(shuffled)
  assert ingest(loaded, "\n".join(ordered)).status_code == 200
  assert ingest(loaded, "\n".join(shuffled[30:])).status_code == 200    # half now ...
  assert ingest(loaded, "\n".join(shuffled[:30])).status_code == 200    # ... the rest arrives late
  a, b = query(loaded, sub("ooo_a"), sub("ooo_b")).json()
  assert a["dps"] == b["dps"] == SUMS_5M


def test_corrected_value_wins(loaded):
  ingest(loaded, "\n".join(lines("fix", "2", [1.0, 1.0])))
  time.sleep(0.01)
  ingest(loaded, f"fix {BASE_S * 1000} 7 ip={IP} intf=2")
  r = query(loaded, sub("fix", downsample="1m-sum"))
  assert r.json()[0]["dps"] == {str(BASE_S): 7.0, str(BASE_S + 60): 1.0}


def test_explicit_tags_off_includes_extra_keys(loaded):
  [res] = query(loaded, sub("in_bw", explicit=False)).json()
  assert res["aggregateTags"] == ["vlan"]
  assert res["dps"][str(BASE_S)] == 10.0 + 5000.0


def test_wildcard_group_by_and_none(loaded):
  r = query(loaded, sub("in_bw", ip=IP, intf="*")).json()
  assert [x["tags"]["intf"] for x in r] == ["2", "3"]
  assert r[1]["dps"][str(BASE_S)] == 500.0
  r = query(loaded, sub("in_bw", aggregator="none", explicit=False, ip=IP, intf="*")).json()
  assert len(r) == 3 and all(x["aggregateTags"] == [] for x in r)


def test_cross_series_aggregators(loaded):
  # intf 2 and 3 combined: a non-grouping filter (tags-map entries always group, as in OpenTSDB)
  def first(agg, ds="5m-sum-nan"):
    q = {"metric": "in_bw", "aggregator": agg, "downsample": ds, "tags": {"ip": IP}, "explicitTags": True,
         "filters": [{"type": "literal_or", "tagk": "intf", "filter": "2|3"}]}
    [res] = query(loaded, q).json()
    assert res["aggregateTags"] == ["intf"]
    return res["dps"][str(BASE_S)]
  assert first("sum") == 510.0 and first("avg") == 255.0
  assert first("min") == 10.0 and first("max") == 500.0 and first("count") == 2.0
  assert first("dev") == 245.0 and first("zimsum") == 510.0 and first("mimmax") == 500.0


def test_downsample_functions(loaded):
  def bucket0(ds):
    return query(loaded, sub("in_bw", downsample=ds)).json()[0]["dps"][str(BASE_S)]
  assert bucket0("5m-avg") == 2.0 and bucket0("5m-min") == 0.0 and bucket0("5m-max") == 4.0
  assert bucket0("5m-count") == 5.0 and bucket0("5m-first") == 0.0 and bucket0("5m-last") == 4.0
  assert bucket0("0all-sum") == float(sum(VALUES))
  assert bucket0("1h-p50") == pytest.approx(29.5)


def test_fill_policies(loaded):
  end = BASE_S + 2 * 3600 - 1        # one hour beyond the data
  for fill, empty in (("nan", None), ("null", None), ("zero", 0.0)):
    [res] = query(loaded, sub("in_bw", downsample=f"1h-sum-{fill}"), end=end).json()
    assert res["dps"] == {str(BASE_S): float(sum(VALUES)), str(BASE_S + 3600): empty}
  [res] = query(loaded, sub("in_bw", downsample="1h-sum"), end=end).json()
  assert list(res["dps"]) == [str(BASE_S)]


def test_raw_points_and_output_options(loaded):
  [res] = query(loaded, sub("in_bw", downsample=None), end=BASE_S + 120).json()
  assert res["dps"] == {str(BASE_S): 0.0, str(BASE_S + 60): 1.0, str(BASE_S + 120): 2.0}
  [res] = query(loaded, sub("in_bw", downsample=None), end=BASE_S + 60, msResolution=True, arrays=True,
                showQuery=True).json()
  assert res["dps"] == [[BASE_S * 1000, 0.0], [(BASE_S + 60) * 1000, 1.0]]
  assert res["query"]["metric"] == "in_bw" and res["query"]["index"] == 0
  # Several sub-queries, even for the same metric: query.index tells their results apart.
  out = query(loaded, sub("nope"), sub("in_bw"), sub("in_bw", downsample="1h-max"), showQuery=True).json()
  assert [r["query"]["index"] for r in out] == [1, 2]


def test_relative_time(loaded):
  r = loaded.post("/api/query", json={"start": "3d-ago", "queries": [sub("in_bw", downsample="1d-sum")]})
  assert r.status_code == 200 and sum(r.json()[0]["dps"].values()) == float(sum(VALUES))


def test_get_matches_post(loaded):
  m = f"sum:5m-sum-nan:explicit_tags:in_bw{{ip={IP},intf=2}}"
  r = loaded.get("/api/query", params={"start": BASE_S, "end": BASE_S + 3599, "m": m})
  assert r.status_code == 200, r.text
  assert r.json() == query(loaded, sub("in_bw")).json()
  r = loaded.get("/api/query", params={"start": BASE_S, "end": BASE_S + 3599,
                                       "m": [m, f"sum:5m-sum:in_bw{{ip={IP},intf=literal_or(3)}}"]})
  assert [x["tags"]["intf"] for x in r.json()] == ["2", "3"]


def test_filters_json(loaded):
  body = {"start": BASE_S, "end": BASE_S + 3599, "queries": [{
    "metric": "in_bw", "aggregator": "sum", "downsample": "1h-count",
    "filters": [{"type": "regexp", "tagk": "intf", "filter": "^[23]$", "groupBy": True},
                {"type": "not_literal_or", "tagk": "ip", "filter": "1.1.1.1"}]}]}
  r = loaded.post("/api/query", json=body).json()
  assert [x["tags"]["intf"] for x in r] == ["2", "3"]
  assert r[0]["aggregateTags"] == ["vlan"]


def test_unknown_metric_is_empty(loaded):
  assert query(loaded, sub("no_such_metric")).json() == []


@pytest.mark.parametrize("change,msg", [
  ({"rate": True}, "rate"),
  ({"aggregator": "median"}, "aggregator"),
  ({"downsample": "1n-sum"}, "not supported"),
  ({"metric": "bad metric"}, "metric"),
])
def test_query_errors(loaded, change, msg):
  r = query(loaded, {**sub("in_bw"), **change})
  assert r.status_code == 400 and msg in r.json()["error"]["message"]


def test_bad_lines_are_reported_and_good_lines_kept(api):
  body = "\n".join([
    f"partial {BASE_S * 1000} 1 ip={IP} intf=9",
    f"partial {BASE_S * 1000} abc ip={IP} intf=9",
    f"partial {BASE_S * 1000} 1",
    f"partial {(int(time.time()) + 86400) * 1000} 1 ip={IP} intf=9",
  ])
  r = ingest(api, body)
  assert r.status_code == 400
  j = r.json()
  assert j["success"] == 1 and j["failed"] == 3
  assert [e["line"] for e in j["errors"]] == [2, 3, 4]
  assert "future" in j["errors"][2]["error"]
  assert ingest(api, body, params={"details": "false"}).json() == {"success": 1, "failed": 3}


def test_gzip_body_and_multipart_upload(api):
  body = ("\n".join(lines("gz", "2", VALUES)) + "\n").encode()   # files end with a newline
  r = api.post("/api/ingest", content=gzip.compress(body), headers={"Content-Encoding": "gzip"})
  assert r.json()["success"] == 60
  r = api.post("/api/ingest", files={"file": ("x.tsdb.gz", gzip.compress(body) + gzip.compress(body))})
  assert r.status_code == 200 and r.json()["success"] == 120      # two concatenated gzip members
  r = api.post("/api/ingest", files={"file": ("x.tsdb", body)})
  assert r.json()["success"] == 60
  assert query(api, sub("gz")).json()[0]["dps"] == SUMS_5M        # still deduplicated


def test_unicode_tags_round_trip(api):
  assert ingest(api, f"thai {BASE_S * 1000} 5 site=กรุงเทพ").status_code == 200
  r = query(api, {"metric": "thai", "aggregator": "sum", "downsample": "1h-sum", "tags": {"site": "กรุงเทพ"}})
  assert r.json()[0]["tags"] == {"site": "กรุงเทพ"}


def test_suggest(loaded):
  assert "in_bw" in loaded.get("/api/suggest", params={"type": "metrics", "q": "in_"}).json()
  assert loaded.get("/api/suggest", params={"type": "tagk", "metric": "in_bw"}).json() == ["intf", "ip", "vlan"]
  assert loaded.get("/api/suggest", params={"type": "tagv", "metric": "in_bw", "tagk": "intf"}).json() == ["2", "3"]
  assert loaded.get("/api/suggest", params={"type": "tagv", "tagk": "ip", "q": "10.163", "max": 1}).json() == [IP]
  assert loaded.get("/api/suggest", params={"type": "bogus"}).status_code == 400


def test_stats(loaded):
  from tsdb.api import meta
  meta._stats_cache.clear()
  j = loaded.get("/api/stats").json()
  assert j["database"] == TEST_DB and j["rows"] > 0 and j["disk_bytes"] > 0 and j["days"] >= 1
  m = {r["metric"]: r for r in j["metrics"]}
  assert m["in_bw"]["series"] == 3 and m["in_bw"]["tag_keys"] == ["intf", "ip", "vlan"]
  assert m["in_bw"]["last_ts"] is None or m["in_bw"]["last_ts"] >= BASE_S * 1000   # data is ~2 days old
  assert j["series"] >= 3


def test_many_series_in_one_query(api):
  # 6000 ids used to overflow ClickHouse's 128 KB form-field limit; they now go as an external table.
  body = "\n".join(f"wide {BASE_S * 1000} 1 ip=10.9.{i // 250}.{i % 250} intf=1" for i in range(6000))
  assert ingest(api, body).json()["success"] == 6000
  r = query(api, {"metric": "wide", "aggregator": "sum", "downsample": "1h-sum"})
  assert r.status_code == 200 and r.json()[0]["dps"] == {str(BASE_S): 6000.0}
  r = query(api, {"metric": "wide", "aggregator": "sum", "downsample": "1h-sum-zero", "tags": {"ip": "*"}})
  assert len(r.json()) == 6000


# ---- Postgres only -------------------------------------------------------------------------------

def test_pg_duplicates_in_one_body_last_line_wins(api, backend):
  if backend != "postgres":
    pytest.skip("ClickHouse rows of one insert tie on ingested_at")
  body = f"dup {BASE_S * 1000} 1 ip={IP} intf=2\ndup {BASE_S * 1000} 5 ip={IP} intf=2"
  assert ingest(api, body).json()["success"] == 2
  assert query(api, sub("dup", downsample="1m-sum")).json()[0]["dps"] == {str(BASE_S): 5.0}


def test_pg_maintenance_drops_expired_partitions_and_applies_retention(api, backend):
  if backend != "postgres":
    pytest.skip("ClickHouse uses TTL rules")
  from tsdb.store import get_store
  store = get_store()
  old_day = int(time.time()) // 86400 - config.get_settings().tsdb_max_retention_days - 2
  old = "points_" + time.strftime("%Y%m%d", time.gmtime(old_day * 86400))

  async def names():
    async with store.pool.acquire() as conn:
      return {r[0] for r in await store._partitions(conn)}

  async def setup():
    await store._ensure_partitions([old_day])
    await store.pool.execute(f"INSERT INTO {TEST_DB}.retention VALUES ($1, 1)", r"ret\_%")

  assert ingest(api, "\n".join(lines("ret_a", "2", VALUES) + lines("keep_a", "2", VALUES))).status_code == 200
  api.portal.call(setup)
  assert old in api.portal.call(names)
  try:
    api.portal.call(store.maintain)
  finally:
    api.portal.call(store.pool.execute, f"DELETE FROM {TEST_DB}.retention")
  assert old not in api.portal.call(names)
  assert query(api, sub("ret_a")).json() == []                   # 2 days old, its rule keeps 1 day
  assert query(api, sub("keep_a")).json()[0]["dps"] == SUMS_5M   # no rule: kept
