"""/api/boards fleet-wide list against the real read-only DB (skipped if unreachable)."""
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


async def test_list_and_filters(client):
  r = (await client.get("/api/boards", params={"size": 10})).json()
  assert r["total"] == await db.fetchval("SELECT count(*) FROM board") and len(r["items"]) <= 10
  assert {"device_name", "device_ip", "boardname", "boardtype", "boardrole", "operstatus", "first", "lastseen"} <= r["items"][0].keys()
  f = (await client.get("/api/boards/facets")).json()
  st = f["operstatus"][0]["value"]
  only = (await client.get("/api/boards", params={"operstatus": st, "size": 200})).json()
  assert only["total"] == f["operstatus"][0]["count"] and all(i["operstatus"] == st for i in only["items"])
  dev = r["items"][0]["device_name"]
  d = (await client.get("/api/boards", params={"device": dev, "sort": "boardname", "size": 200})).json()
  assert d["total"] >= 1 and all(dev.lower() in i["device_name"].lower() for i in d["items"])


async def test_validation(client):
  assert (await client.get("/api/boards", params={"size": 201})).status_code == 422
  assert (await client.get("/api/boards", params={"sort": "nope", "size": 1})).status_code == 200
