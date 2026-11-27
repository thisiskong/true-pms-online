import pytest

from tsdb.query import assemble
from tsdb.query.parse import (Downsample, QueryError, TagFilter, check_aggregator, check_filter,
                              parse_downsample, parse_time, percentile, tags_to_filters)
from tsdb.query.plan import aggregate_in_sql, points_sql, sel_table
from tsdb.query.resolve import resolve_sql, wildcard_to_like

NOW = 1_795_626_000_000


@pytest.mark.parametrize("v,expect", [
  (1764090000, 1764090000000),
  (1764090000123, 1764090000123),
  ("1764090000", 1764090000000),
  ("now", NOW),
  (None, NOW),
  ("1h-ago", NOW - 3_600_000),
  ("7d-ago", NOW - 7 * 86_400_000),
  ("30s-ago", NOW - 30_000),
])
def test_parse_time(v, expect):
  assert parse_time(v, NOW, "start") == expect


@pytest.mark.parametrize("v", ["yesterday", "1x-ago", -5, True, "12.5"])
def test_parse_time_rejects(v):
  with pytest.raises(QueryError):
    parse_time(v, NOW, "start")


@pytest.mark.parametrize("spec,expect", [
  ("5m-sum-nan", Downsample(300, "sum", "nan")),
  ("5m-avg", Downsample(300, "avg", "none")),
  ("1h-max-zero", Downsample(3600, "max", "zero")),
  ("30s-count-null", Downsample(30, "count", "null")),
  ("1w-last", Downsample(604800, "last", "none")),
  ("0all-sum", Downsample(0, "sum", "none")),
  ("1d-p95", Downsample(86400, "p95", "none")),
])
def test_parse_downsample(spec, expect):
  assert parse_downsample(spec) == expect


@pytest.mark.parametrize("spec,msg", [
  ("5m", "invalid downsample"),
  ("5x-sum", "invalid downsample unit"),
  ("1n-sum", "not supported"),
  ("1dc-sum", "not supported"),
  ("100ms-sum", "not supported"),
  ("5m-median", "unsupported downsample function"),
  ("5m-sum-linear", "unsupported fill"),
  ("0m-sum", "> 0"),
  ("5all-sum", "0all"),
])
def test_parse_downsample_rejects(spec, msg):
  with pytest.raises(QueryError, match=msg):
    parse_downsample(spec)


def test_percentiles():
  assert percentile("p50") == 0.5 and percentile("p99") == 0.99 and percentile("p999") == 0.999


def test_aggregators():
  assert check_aggregator("zimsum") == "zimsum"
  with pytest.raises(QueryError, match="supported"):
    check_aggregator("median")


def test_tags_become_group_by_filters():
  fs = tags_to_filters({"ip": "10.0.0.1", "intf": "*", "vlan": "1|2", "host": "ab*"})
  assert [(f.tagk, f.type, f.group_by) for f in fs] == [
    ("ip", "literal_or", True), ("intf", "wildcard", True),
    ("vlan", "literal_or", True), ("host", "wildcard", True)]
  assert fs[2].values == ["1", "2"]


def test_check_filter():
  with pytest.raises(QueryError, match="unsupported filter type"):
    check_filter(TagFilter("a", "iliteral_or", "x", False))
  with pytest.raises(QueryError, match="invalid tag key"):
    check_filter(TagFilter("a b", "literal_or", "x", False))


def test_wildcard_to_like_escapes():
  assert wildcard_to_like("ab*") == "ab%"
  assert wildcard_to_like("a_b%*") == "a\\_b\\%%"


def test_resolve_sql_explicit():
  sql, params = resolve_sql("tsdb", "in_bw", tags_to_filters({"ip": "10.0.0.1", "intf": "2"}), True, 100)
  assert "HAVING uniqExact(tag_key) = 2" in sql and "length(tags) = 2" in sql and "LIMIT 101" in sql
  assert "10.0.0.1" not in sql                       # values are bound, never inlined
  assert ["10.0.0.1"] in params.values() and ["2"] in params.values()


def test_resolve_sql_not_literal_or_and_wildcard():
  fs = [TagFilter("intf", "wildcard", "*", True), TagFilter("ip", "not_literal_or", "1|2", False)]
  sql, params = resolve_sql("tsdb", "m", fs, False, 10)
  assert "NOT has(" in sql and "length(tags)" not in sql and "LIKE" not in sql
  assert ["1", "2"] in params.values()


def test_resolve_sql_explicit_without_tags_is_rejected():
  with pytest.raises(QueryError, match="explicitTags"):
    resolve_sql("tsdb", "m", [], True, 10)


def test_resolve_sql_regexp_is_checked():
  with pytest.raises(QueryError, match="invalid regexp"):
    resolve_sql("tsdb", "m", [TagFilter("a", "regexp", "(", False)], False, 10)


def test_sql_or_python_aggregation():
  assert aggregate_in_sql("sum", Downsample(300, "sum", "nan"))
  assert aggregate_in_sql("dev", None)
  assert not aggregate_in_sql("sum", Downsample(300, "sum", "zero"))
  assert not aggregate_in_sql("zimsum", Downsample(300, "sum", "nan"))
  assert not aggregate_in_sql("none", None)


def test_points_sql_shapes():
  sql, _ = points_sql("tsdb", "m", [1, 2], [0, 0], 0, 10, Downsample(300, "p95", "nan"), "sum", True, 5)
  assert "argMax(value, ingested_at)" in sql and "quantile(0.95)(v)" in sql and "JOIN _sel" in sql
  sql, _ = points_sql("tsdb", "m", [1], None, 0, 10, None, "none", False, 5)
  assert "argMax(value, ingested_at)" not in sql and "JOIN _sel" not in sql and "FROM _sel" in sql
  assert sel_table([7, 2**64 - 1], [0, 3]) == b"7\t0\n18446744073709551615\t3\n"


def test_fill_buckets_and_count():
  ds = Downsample(300, "sum", "nan")
  b = assemble.fill_buckets(ds, 1_000_000, 2_000_000)
  assert b[0] == 900_000 and b[-1] == 1_800_000 and len(b) == assemble.bucket_count(ds, 1_000_000, 2_000_000)
  assert assemble.fill_buckets(Downsample(300, "sum", "none"), 0, 10) is None
  assert assemble.fill_buckets(Downsample(0, "sum", "zero"), 123, 999) == [123]


def test_groups_and_aggregate_tags():
  series = [(1, {"ip": "a", "intf": "1"}), (2, {"ip": "a", "intf": "2"}), (3, {"ip": "b", "intf": "1"})]
  gs = assemble.make_groups(series, ["ip"], "sum")
  assert [g.key for g in gs] == [("a",), ("b",)]
  assert assemble.group_tags(gs[0]) == ({"ip": "a"}, ["intf"])
  assert assemble.group_tags(gs[1]) == ({"intf": "1", "ip": "b"}, [])
  assert len(assemble.make_groups(series, ["ip"], "none")) == 3


def test_python_aggregation_fill_policies():
  g = assemble.Group(("x",), [(1, {}), (2, {})])
  per = {1: {0: 1.0, 300_000: 2.0}, 2: {0: 10.0}}
  nan = Downsample(300, "sum", "nan")
  buckets = assemble.fill_buckets(nan, 0, 600_000)
  assert assemble.aggregate_python(g, per, "zimsum", nan, buckets) == {0: 11.0, 300_000: 2.0, 600_000: 0.0}
  assert assemble.aggregate_python(g, per, "mimmin", nan, buckets) == {0: 1.0, 300_000: 2.0, 600_000: None}
  zero = Downsample(300, "sum", "zero")
  assert assemble.aggregate_python(g, per, "avg", zero, buckets) == {0: 5.5, 300_000: 1.0, 600_000: 0.0}
  assert assemble.aggregate_python(g, per, "sum", None, None) == {0: 11.0, 300_000: 2.0}


def test_format_dps():
  dps = {1_000_000: 1.0, 1_300_000: None}
  assert assemble.format_dps(dps, False, False) == {"1000": 1.0, "1300": None}
  assert assemble.format_dps(dps, True, True) == [[1_000_000, 1.0], [1_300_000, None]]


# ---- GET /api/query URL syntax ----

from tsdb.query.url import parse_m  # noqa: E402


def test_parse_m_full():
  q = parse_m("avg:1h-max-nan:explicit_tags:in_bw{ip=10.163.193.127,intf=2}")
  assert (q.aggregator, q.downsample, q.explicitTags, q.metric) == ("avg", "1h-max-nan", True, "in_bw")
  assert q.tags == {"ip": "10.163.193.127", "intf": "2"} and q.filters == []


def test_parse_m_minimal_and_functions():
  q = parse_m("sum:in_bw")
  assert q.metric == "in_bw" and q.downsample is None and q.tags == {}
  q = parse_m(r"sum:5m-avg:in_bw{intf=literal_or(1|2),ip=regexp(^10\.1{2}),x=*}{host=ab*}")
  assert q.tags == {"x": "*"}
  assert [(f.tagk, f.type, f.filter, f.groupBy) for f in q.filters] == [
    ("intf", "literal_or", "1|2", True), ("ip", "regexp", r"^10\.1{2}", True), ("host", "wildcard", "ab*", False)]


def test_parse_m_rate_flag_and_errors():
  assert parse_m("sum:rate:in_octets").rate is True
  for bad in ["in_bw", "sum:", "sum:bogus:in_bw", "sum:in_bw{ip}"]:
    with pytest.raises(QueryError):
      parse_m(bad)


# ---- Postgres SQL -------------------------------------------------------------------------------

from tsdb.store import pg_sql  # noqa: E402


def test_pg_resolve_sql_explicit():
  sql, params = pg_sql.resolve_sql("tsdb", "in_bw", tags_to_filters({"ip": "10.0.0.1", "intf": "2"}), True, 100)
  assert "HAVING count(DISTINCT tag_key) = 2" in sql and "s.n_tags = 2" in sql and "LIMIT 101" in sql
  assert "10.0.0.1" not in sql and ["10.0.0.1"] in params and ["2"] in params
  assert sql.count("$") == len(params) + 1           # $1 (metric) is used twice


def test_pg_resolve_sql_filters():
  fs = [TagFilter("intf", "wildcard", "a_*", True), TagFilter("ip", "not_literal_or", "1|2", False),
        TagFilter("x", "regexp", "^1", False)]
  sql, params = pg_sql.resolve_sql("tsdb", "m", fs, False, 10)
  assert "tag_value LIKE $" in sql and "a\_%" in params and "tag_value ~ $" in sql
  assert "NOT (s.tags ->> $" in sql and ["1", "2"] in params and "n_tags" not in sql
  with pytest.raises(QueryError, match="explicitTags"):
    pg_sql.resolve_sql("tsdb", "m", [], True, 10)


def test_pg_points_sql_shapes():
  sql, params = pg_sql.points_sql("tsdb", [1, -2], [0, 0], 0, 10, Downsample(300, "p95", "nan"), "sum", 5)
  assert "percentile_cont(0.95) WITHIN GROUP (ORDER BY v)" in sql and "unnest($1::bigint[], $4::int[])" in sql
  assert "/ 300000) * 300000" in sql and params == [[1, -2], 0, 10, [0, 0]]
  sql, _ = pg_sql.points_sql("tsdb", [1], None, 0, 10, Downsample(0, "last", "none"), "none", 5)
  assert "array_agg(v ORDER BY ts DESC)" in sql and "unnest" not in sql and "$2::bigint AS bucket" in sql


def test_pg_series_id_sign_round_trip():
  for sid in (0, 1, 2**63 - 1, 2**63, 2**64 - 1):
    signed = pg_sql.to_signed(sid)
    assert -2**63 <= signed < 2**63 and pg_sql.to_unsigned(signed) == sid
