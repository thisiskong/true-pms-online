"""/api/network health lists against the real read-only DB (skipped if unreachable)."""
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


async def test_reboots_paging_and_order(client):
  r = (await client.get("/api/network/reboots", params={"since_hours": 720, "size": 5})).json()
  assert r["page"] == 1 and r["size"] == 5 and len(r["items"]) <= 5
  times = [i["uptime"]["last_reboot_at"] for i in r["items"]]
  assert times == sorted(times, reverse=True)
  if r["total"] > 5:
    p2 = (await client.get("/api/network/reboots", params={"since_hours": 720, "size": 5, "page": 2})).json()
    assert {i["id"] for i in p2["items"]}.isdisjoint({i["id"] for i in r["items"]})


async def test_unreachable_never_toggle(client):
  with_never = (await client.get("/api/network/unreachable", params={"size": 1})).json()["total"]
  without = (await client.get("/api/network/unreachable", params={"size": 1, "include_never": "false"})).json()
  assert without["total"] <= with_never
  assert all(i["uptime"]["last_ping_success_at"] for i in without["items"])


async def test_validation(client):
  assert (await client.get("/api/network/reboots", params={"since_hours": 0})).status_code == 422
  assert (await client.get("/api/network/unreachable", params={"size": 999})).status_code == 422


async def test_unstable_counts_and_order(client):
  r = (await client.get("/api/network/unstable", params={"since_hours": 720, "min_changes": 1, "size": 20})).json()
  items = r["items"]
  assert r["total"] >= len(items)
  keys = [(-i["changes"], i["last_change"]) for i in items]
  assert [k[0] for k in keys] == sorted(k[0] for k in keys)
  for i in items:
    assert i["changes"] >= 1 and i["down_changes"] <= i["oper_changes"] <= i["changes"]
  stricter = (await client.get("/api/network/unstable", params={"since_hours": 720, "min_changes": 3, "size": 1})).json()
  assert stricter["total"] <= r["total"]
  assert all(i["changes"] >= 3 for i in stricter["items"])


async def test_unstable_excludes_first_sighting(client):
  # rev 1 is when an interface was first seen; an interface whose only row in the window is rev 1 has no changes.
  row = await db.fetchrow(
    """SELECT r.id FROM intf_rev r WHERE r.rev = 1 AND r.first > now() - interval '30 days'
       AND NOT EXISTS (SELECT 1 FROM intf_rev x WHERE x.id = r.id AND x.rev > 1) LIMIT 1""")
  if row is None:
    pytest.skip("no first-sighting-only interface in the last 30 days")
  dev = int(row["id"].split(".")[0])
  name = await db.fetchval("SELECT name FROM device WHERE id = $1", dev)
  r = (await client.get("/api/network/unstable", params={"since_hours": 720, "min_changes": 1, "q": name, "size": 200})).json()
  assert row["id"] not in {i["id"] for i in r["items"]}


async def test_unstable_validation(client):
  assert (await client.get("/api/network/unstable", params={"since_hours": 2161})).status_code == 422
  assert (await client.get("/api/network/unstable", params={"min_changes": 0})).status_code == 422
