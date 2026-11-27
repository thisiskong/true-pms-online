"""/api/interfaces fleet-wide list against the real read-only DB (skipped if unreachable)."""
import pytest
from httpx import ASGITransport, AsyncClient

from app import db
from app.main import api


@pytest.fixture
async def client():
  try:
    await db.open_pool()
  except Exception as e:  # pragma: no cover
    pytest.skip(f"database unreachable: {e}")
  async with AsyncClient(transport=ASGITransport(app=api), base_url="http://t") as c:
    yield c
  await db.close_pool()


async def test_default_page_sorted_by_name(client):
  r = (await client.get("/api/interfaces", params={"size": 20})).json()
  assert r["total"] > 1_000_000 and len(r["items"]) == 20
  # Order is the DB collation's (locale-aware), so compare with the DB rather than Python's sorted().
  names = [i["name"] for i in r["items"]]
  for a, b in zip(names, names[1:]):
    assert await db.fetchval("SELECT $1::varchar <= $2::varchar", a, b)
  assert {"device_name", "device_ip", "altname", "ifspeed", "speed_text", "dsttype", "dstsite", "dstport", "moduleclass", "lastseen"} <= r["items"][0].keys()


async def test_device_and_filters(client):
  dev = await db.fetchrow("SELECT d.name, count(*) AS c FROM device d JOIN intf i ON i.device_id = d.id WHERE d.name = 'KKN25002G00' GROUP BY 1")
  if dev is None:
    pytest.skip("sample device missing")
  r = (await client.get("/api/interfaces", params={"device": "KKN25002G00", "size": 200})).json()
  assert r["total"] == dev["c"] and all(i["device_name"] == "KKN25002G00" for i in r["items"])
  up = (await client.get("/api/interfaces", params={"device": "KKN25002G00", "ifoper": "up", "size": 200})).json()
  assert up["total"] <= r["total"] and all(i["ifoper"] == "up" for i in up["items"])
  olt = (await client.get("/api/interfaces", params={"dsttype": "OLT", "size": 5, "sort": "lastseen", "order": "desc"})).json()
  assert all(i["dsttype"] == "OLT" for i in olt["items"])
  times = [i["lastseen"] for i in olt["items"]]
  assert times == sorted(times, reverse=True)


async def test_facets_and_validation(client):
  f = (await client.get("/api/interfaces/facets")).json()
  assert any(x["value"] == "up" for x in f["ifoper"]) and f["dsttype"] and len(f["moduleclass"]) <= 80
  assert (await client.get("/api/interfaces", params={"size": 201})).status_code == 422
  assert (await client.get("/api/interfaces", params={"order": "sideways"})).status_code == 422
  # Unknown sort keys fall back to name (whitelisted, never interpolated); long ones are rejected.
  assert (await client.get("/api/interfaces", params={"sort": "name;drop", "size": 1})).status_code == 200
  assert (await client.get("/api/interfaces", params={"sort": "x" * 21})).status_code == 422
