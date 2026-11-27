"""/tsdb/api/* proxy against a fake tsdb (no network, no DB)."""
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api import tsdb_proxy
from app.config import get_settings
from app.main import api

seen: list[httpx.Request] = []


def fake_tsdb(req: httpx.Request) -> httpx.Response:
  seen.append(req)
  if req.url.path == "/api/stats":
    return httpx.Response(200, json={"backend": "clickhouse", "rows": 3})
  if req.url.path == "/api/query":
    return httpx.Response(200, json=[{"metric": "in_bw", "echo": json.loads(req.content or b"null")}])
  if req.url.path == "/api/suggest":
    return httpx.Response(200, json=sorted(req.url.params.get_list("q")))
  return httpx.Response(404, json={"detail": "nope"})


@pytest.fixture
async def client(monkeypatch):
  seen.clear()
  monkeypatch.setattr(tsdb_proxy, "_client", httpx.AsyncClient(base_url="http://tsdb", transport=httpx.MockTransport(fake_tsdb)))
  async with AsyncClient(transport=ASGITransport(app=api), base_url="http://t") as c:
    yield c
  await tsdb_proxy.close()


async def test_get_forwarded(client):
  r = await client.get("/tsdb/api/stats")
  assert r.status_code == 200 and r.json()["rows"] == 3
  assert seen[-1].url.path == "/api/stats"


async def test_post_query_body_and_repeated_params(client):
  r = await client.post("/tsdb/api/query", json={"start": "1h-ago"})
  assert r.json()[0]["echo"] == {"start": "1h-ago"}
  r = await client.get("/tsdb/api/suggest", params=[("q", "b"), ("q", "a")])
  assert r.json() == ["a", "b"]


@pytest.mark.parametrize("method,path", [
  ("POST", "/tsdb/api/ingest"),       # write endpoint is never proxied
  ("GET", "/tsdb/api/ingest"),
  ("POST", "/tsdb/api/stats"),        # wrong method
  ("GET", "/tsdb/api/query/extra"),   # multi-segment
  ("GET", "/tsdb/admin"),
  ("DELETE", "/tsdb/api/query"),
])
async def test_blocked(client, method, path):
  r = await client.request(method, path, content=b"x 1 1 a=b")
  assert r.status_code == 404 and "detail" in r.json()
  assert seen == []


async def test_traversal_not_forwarded(client):
  # httpx normalises "/tsdb/api/../../admin" to "/admin" before sending; either way tsdb must see nothing.
  await client.get("/tsdb/api/../../admin")
  await client.get("/tsdb/api/%2e%2e%2fadmin")
  assert all(req.url.path in {"/api/health", "/api/stats", "/api/suggest", "/api/query"} for req in seen)


async def test_api_key_added_server_side(client, monkeypatch):
  monkeypatch.setattr(get_settings(), "tsdb_api_key", "s3cret")
  await client.get("/tsdb/api/stats", headers={"x-api-key": "from-browser"})
  assert seen[-1].headers["x-api-key"] == "s3cret"


async def test_unreachable_is_502(monkeypatch):
  def down(req):
    raise httpx.ConnectError("refused", request=req)
  monkeypatch.setattr(tsdb_proxy, "_client", httpx.AsyncClient(base_url="http://tsdb", transport=httpx.MockTransport(down)))
  async with AsyncClient(transport=ASGITransport(app=api), base_url="http://t") as c:
    r = await c.get("/tsdb/api/stats")
  assert r.status_code == 502
  await tsdb_proxy.close()
