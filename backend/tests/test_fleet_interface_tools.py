"""Fleet-wide interface tools (search_interfaces / count_interfaces) against the real read-only DB."""
import pytest

from app import db
from app.tools.registry import MCP_TOOLS, TOOLS_BY_NAME, ToolInputError


@pytest.fixture
async def pool():
  try:
    await db.open_pool()
  except Exception as e:  # pragma: no cover
    pytest.skip(f"database unreachable: {e}")
  yield
  await db.close_pool()


async def test_registered_and_validates():
  names = {t.name for t in MCP_TOOLS}
  assert {"search_interfaces", "count_interfaces"} <= names
  for bad in ({"oper": "sideways"}, {"group_by": "colour"}, {"limit": 0}, {"min_speed_mbps": -1}, {"nope": 1}):
    with pytest.raises(ToolInputError):
      await TOOLS_BY_NAME["count_interfaces"].run(bad)


async def test_olt_counts_match_sql(pool):
  r = await TOOLS_BY_NAME["count_interfaces"].run({"topology": "OLT", "group_by": "oper"})
  expected = await db.fetchval(
    "SELECT count(*) FROM intf i JOIN device d ON d.id = i.device_id WHERE d.topology = 'OLT'")
  assert r["total"] == expected and sum(g["count"] for g in r["groups"]) == expected
  down = await TOOLS_BY_NAME["count_interfaces"].run({"topology": "OLT", "oper": "down"})
  assert down["total"] == next(g["count"] for g in r["groups"] if g["value"] == "down")


async def test_search_rows_respect_filters(pool):
  r = await TOOLS_BY_NAME["search_interfaces"].run({"topology": "OLT", "oper": "down", "min_speed_mbps": 10000, "limit": 20})
  assert r["total"] >= len(r["items"])
  for i in r["items"]:
    assert i["topology"] == "OLT" and i["ifoper"] == "down"
  # Device filter + region grouping works through the device join.
  g = await TOOLS_BY_NAME["count_interfaces"].run({"topology": "OLT", "oper": "down", "min_speed_mbps": 10000, "group_by": "region"})
  assert g["total"] == r["total"]


async def test_group_by_device_includes_identity(pool):
  r = await TOOLS_BY_NAME["count_interfaces"].run({"topology": "OLT", "oper": "down", "group_by": "device", "limit": 5})
  assert len(r["groups"]) <= 5 and r["devices"] >= len(r["groups"])
  g = r["groups"][0]
  assert {"device_id", "value", "ip", "vendor", "model", "region", "count"} <= g.keys()
  counts = [x["count"] for x in r["groups"]]
  assert counts == sorted(counts, reverse=True)
