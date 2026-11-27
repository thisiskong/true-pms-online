import pytest

from tsdb.ingest.parser import LineError, canonical_series, parse_line
from tsdb.ingest.series import SeriesCache, series_id
from tsdb.ingest.writer import Batch, CollisionError

MIN, MAX = 0, 9_999_999_999_999


def p(line, max_tags=8, lo=MIN, hi=MAX):
  return parse_line(line, lo, hi, max_tags)


def test_ms_line():
  pt = p("in_bw 1795626000000 0.506805440000000 ip=10.177.152.19 intf=73")
  assert pt.metric == "in_bw" and pt.ts_ms == 1795626000000 and pt.value == pytest.approx(0.50680544)
  assert pt.tags == {"ip": "10.177.152.19", "intf": "73"}


def test_seconds_are_converted_to_ms():
  assert p("m 1795626000 1 a=b").ts_ms == 1795626000000


def test_integer_and_negative_values():
  assert p("m 1795626000 123456789 a=b").value == 123456789
  assert p("m 1795626000 -1.5e3 a=b").value == -1500


def test_canonical_form_ignores_tag_order():
  a, b = p("m 1795626000 1 ip=1 intf=2"), p("m 1795626000 1 intf=2 ip=1")
  assert a.canonical == b.canonical == canonical_series("m", {"intf": "2", "ip": "1"})
  assert series_id(a.canonical) == series_id(b.canonical)
  assert series_id(a.canonical) != series_id(p("n 1795626000 1 ip=1 intf=2").canonical)


def test_unicode_tag_value():
  assert p("m 1795626000 1 site=กรุงเทพ").tags == {"site": "กรุงเทพ"}


@pytest.mark.parametrize("line,msg", [
  ("m 1795626000", "expected"),
  ("m 1795626000 1", "at least one tag"),
  ("m 17956x6000 1 a=b", "invalid timestamp"),
  ("m -1795626000 1 a=b", "invalid timestamp"),
  ("m 99999999999999 1 a=b", "invalid timestamp"),
  ("m 1795626000 abc a=b", "not a number"),
  ("m 1795626000 1_0 a=b", "not a number"),
  ("m 1795626000 nan a=b", "finite"),
  ("m 1795626000 inf a=b", "finite"),
  ("m 1795626000 1 a", "invalid tag"),
  ("m 1795626000 1 a=", "invalid tag"),
  ("m 1795626000 1 =b", "invalid tag"),
  ("m 1795626000 1 a=b a=c", "duplicate"),
  ("m 1795626000 1 a=b,c", "invalid characters"),
  ("bad,metric 1795626000 1 a=b", "invalid metric"),
])
def test_rejected(line, msg):
  with pytest.raises(LineError, match=msg):
    p(line)


def test_too_many_tags():
  with pytest.raises(LineError, match="too many tags"):
    p("m 1795626000 1 a=1 b=2 c=3", max_tags=2)


def test_time_window():
  with pytest.raises(LineError, match="future"):
    p("m 1795626000 1 a=b", hi=1795625999999)
  with pytest.raises(LineError, match="older"):
    p("m 1795626000 1 a=b", lo=1795626000001)


def test_batch_registers_each_series_once():
  cache = SeriesCache(100)
  b = Batch(cache)
  for ts in (1795626000, 1795626300):
    b.add(p(f"m {ts} 1 ip=1 intf=2"))
  b.add(p("m 1795626000 1 ip=1 intf=3"))
  assert len(b) == 3 and len(b.new_series) == 2 and len(cache) == 2
  b.clear()
  b.add(p("m 1795626600 1 ip=1 intf=2"))
  assert b.new_series == {}          # already registered by this worker


def test_batch_detects_collision():
  cache = SeriesCache(100)
  pt = p("m 1795626000 1 ip=1")
  cache.add(series_id(pt.canonical), "something else")
  with pytest.raises(CollisionError):
    Batch(cache).add(pt)


def test_batch_splits_wide_time_ranges_by_day():
  b = Batch(SeriesCache(100))
  for day in range(120):
    b.add(p(f"m {1700000000 + day * 86400} {day} a=b", lo=0))
  chunks = list(b._chunks_by_day())
  assert len(chunks) == 3
  assert sum(len(c[2]) for c in chunks) == 120
  for c in chunks:
    days = {t // 86_400_000 for t in c[2]}
    assert max(days) - min(days) < 50
