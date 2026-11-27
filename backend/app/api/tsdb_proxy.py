"""Read-only reverse proxy to the tsdb service (service/tsdb), so the browser reaches it through the backend.

  browser  /tsdb/api/<endpoint>  ->  {TSDB_URL}/api/<endpoint>

Only the read endpoints the TSDB page uses are forwarded. /api/ingest is not: collectors post to tsdb directly.
The backend adds X-API-Key from its own TSDB_API_KEY, so the key never reaches the browser.
"""
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.config import get_settings

log = logging.getLogger(__name__)

router = APIRouter(tags=["tsdb"])

ALLOWED = {("GET", "health"), ("GET", "stats"), ("GET", "suggest"), ("GET", "query"), ("POST", "query")}
MAX_BODY = 1 << 20  # 1 MiB: a query body is a few KB

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
  global _client
  if _client is None:
    s = get_settings()
    # trust_env=False: never route internal tsdb traffic through HTTP(S)_PROXY meant for the LLM.
    _client = httpx.AsyncClient(base_url=s.tsdb_url.rstrip("/"), timeout=s.tsdb_timeout_s, trust_env=False)
  return _client


async def close() -> None:
  global _client
  if _client is not None:
    await _client.aclose()
    _client = None


def _error(status: int, msg: str) -> JSONResponse:
  return JSONResponse({"detail": msg}, status_code=status)


@router.api_route("/tsdb/api/{endpoint}", methods=["GET", "POST"], include_in_schema=False)
async def proxy(endpoint: str, request: Request) -> Response:
  # {endpoint} matches one path segment only, so nothing outside /api/<name> on tsdb is reachable.
  if (request.method, endpoint) not in ALLOWED:
    return _error(404, f"tsdb endpoint not available through the backend: {request.method} /api/{endpoint}")

  headers = {"accept": "application/json"}
  body = b""
  if request.method == "POST":
    body = await request.body()
    if len(body) > MAX_BODY:
      return _error(413, "request body too large")
    headers["content-type"] = request.headers.get("content-type", "application/json")
  key = get_settings().tsdb_api_key
  if key:
    headers["x-api-key"] = key

  try:
    r = await client().request(
      request.method, f"/api/{endpoint}", params=list(request.query_params.multi_items()), content=body, headers=headers,
    )
  except httpx.TimeoutException:
    return _error(504, "tsdb service timed out")
  except httpx.HTTPError as e:
    log.warning("tsdb proxy: %s", e)
    return _error(502, "tsdb service is not reachable")

  return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))


@router.api_route("/tsdb/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def not_proxied(rest: str) -> Response:
  # Anything else under /tsdb is a 404 here, not the SPA's index.html.
  return _error(404, f"not available through the backend: /tsdb/{rest}")
