"""Integration tests against the real read-only database. Skipped when it is unreachable."""
import pytest
from httpx import ASGITransport, AsyncClient

from app import db
from app.config import get_settings
from app.tools.registry import TOOLS_BY_NAME, ToolInputError


@pytest.fixture
async def pool():
  try:
    await db.open_pool()
  except Exception as e:  # pragma: no cover
    pytest.skip(f"database unreachable: {e}")
  yield
  await db.close_pool()


async def test_session_is_read_only(pool):
  assert await db.fetchval("SHOW default_transaction_read_only") == "on"
  with pytest.raises(Exception) as ei:
    await db.fetchval("CREATE TEMP TABLE should_fail(a int)")
  assert "read-only" in str(ei.value).lower()


async def test_community_never_exposed(pool):
  from app.queries import devices
  page = await devices.list_devices(devices.DeviceFilters(), 1, 1)
  d = await devices.get_device(page.items[0].id)
  assert "community" not in d.model_dump()


async def test_tools_end_to_end(pool):
  r = await TOOLS_BY_NAME["search_devices"].run({"topology": "OLT", "limit": 3})
  assert len(r["items"]) == 3 and r["total"] > 3 and r["truncated"]
  dev_id = r["items"][0]["id"]
  d = await TOOLS_BY_NAME["get_device"].run({"device_id": dev_id})
  assert d["device"]["id"] == dev_id
  s = await TOOLS_BY_NAME["interface_summary"].run({"device_id": dev_id})
  assert s["summary"]["total"] >= 0
  c = await TOOLS_BY_NAME["count_devices"].run({"group_by": "vendor"})
  assert c["total"] > 0 and c["groups"]
  with pytest.raises(ToolInputError):
    await TOOLS_BY_NAME["get_device"].run({"device_id": -1})
  with pytest.raises(ToolInputError):
    await TOOLS_BY_NAME["list_interface_changes"].run({})


async def test_rest_api(pool):
  from app.main import api
  async with AsyncClient(transport=ASGITransport(app=api), base_url="http://t") as c:
    r = await c.get("/api/devices", params={"size": 5, "network": "FTTx", "sort": "lastseen", "order": "desc"})
    assert r.status_code == 200 and len(r.json()["items"]) == 5
    dev = r.json()["items"][0]["id"]
    assert (await c.get(f"/api/devices/{dev}")).status_code == 200
    assert (await c.get(f"/api/devices/{dev}/interfaces/summary")).status_code == 200
    assert (await c.get(f"/api/devices/{dev}/interfaces", params={"size": 10})).status_code == 200
    assert (await c.get(f"/api/devices/{dev}/changes")).status_code == 200
    assert (await c.get("/api/devices/facets")).status_code == 200
    assert (await c.get("/api/devices", params={"sort": "community"})).status_code == 422
    assert (await c.get("/api/devices/-5")).status_code == 404


async def test_facets_follow_other_filters(pool):
  from app.queries import devices
  f = devices.DeviceFilters(vendor="ZTE")
  fac = await devices.all_facets(f)
  total = (await devices.list_devices(f, 1, 1)).total
  # other facets are narrowed by vendor=ZTE ...
  assert sum(g["count"] for g in fac["pollstatus"]) == total
  # ... but the vendor facet ignores its own filter, so other vendors stay selectable
  assert len(fac["vendor"]) > 1 and any(g["value"] == "ZTE" and g["count"] == total for g in fac["vendor"])


async def test_kpis_follow_filters(pool):
  from app.queries import devices, stats
  f = devices.DeviceFilters(vendor="ZTE", network="FTTx")
  k = await stats.kpis(f)
  assert k["filtered"] and k["devices"] == (await devices.list_devices(f, 1, 1)).total
  all_k = await stats.kpis()
  assert not all_k["filtered"] and all_k["devices"] > k["devices"]
  assert k["uptime"]["with_uptime"] <= all_k["uptime"]["with_uptime"]
