"""Entry point: `uv run uvicorn app.main:app --port 8000`.

`app` is a small ASGI dispatcher:
  /mcp        -> MCP Streamable HTTP server (bearer token required)
  everything  -> FastAPI (REST API, chat SSE, and the built React app if frontend/dist exists)
"""
import hmac
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings

from app import db
from app.api import access, board, chat, devices, fiber, interfaces, network, stats
from app.config import get_settings
from app.mcp_server.server import mcp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()

mcp_app = mcp.streamable_http_app(
  streamable_http_path="/mcp",
  stateless_http=True,
  json_response=True,
  # Host/Origin checks are for unauthenticated localhost servers; this endpoint requires a bearer token.
  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@asynccontextmanager
async def lifespan(_: FastAPI):
  await db.open_pool()
  async with mcp.session_manager.run():
    yield
  await db.close_pool()


api = FastAPI(title="PMS Online prototype API", version="0.1.0", lifespan=lifespan)
api.add_middleware(
  CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"],
)
api.include_router(devices.router)
api.include_router(stats.router)
api.include_router(fiber.router)
api.include_router(access.router)
api.include_router(network.router)
api.include_router(interfaces.router)
api.include_router(board.router)
api.include_router(chat.router)

# Serve the production React build (frontend/dist) when present; SPA fallback to index.html.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
  api.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

  @api.get("/{path:path}", include_in_schema=False)
  async def spa(path: str) -> FileResponse:
    f = DIST / path
    if path and not path.startswith("api/") and f.is_file() and DIST in f.resolve().parents:
      return FileResponse(f)
    return FileResponse(DIST / "index.html")


async def _deny(send: Any, status: int, msg: str) -> None:
  body = json.dumps({"error": msg}).encode()
  await send({"type": "http.response.start", "status": status, "headers": [
    (b"content-type", b"application/json"), (b"www-authenticate", b'Bearer realm="pms-mcp"'),
  ]})
  await send({"type": "http.response.body", "body": body})


def _token_ok(scope: dict[str, Any]) -> bool:
  tokens = settings.mcp_token_list
  auth = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
  if not auth.lower().startswith("bearer "):
    return False
  given = auth[7:].strip()
  return any(hmac.compare_digest(given, t) for t in tokens)


async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
  path = scope.get("path", "")
  if scope["type"] == "http" and (path == "/mcp" or path.startswith("/mcp/")):
    if not settings.mcp_token_list:
      return await _deny(send, 503, "MCP endpoint disabled: set MCP_TOKENS")
    if not _token_ok(scope):
      return await _deny(send, 401, "missing or invalid bearer token")
    return await mcp_app(scope, receive, send)
  await api(scope, receive, send)
