"""HTTP endpoints: POST /api/ingest, POST /api/query, GET /api/health."""
import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
import orjson
from fastapi.responses import Response
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from ..config import Settings, get_settings
from ..ingest.pipeline import BodyTooLarge, IngestResult, ingest_stream
from ..ingest.series import SeriesCache
from ..query.models import QueryIn
from ..query.parse import QueryError
from ..query.run import run_query
from ..query.url import parse_m
from ..store import get_store

log = logging.getLogger("tsdb")
router = APIRouter()


class ORJSONResponse(Response):
  media_type = "application/json"

  def render(self, content) -> bytes:
    return orjson.dumps(content)
_cache: SeriesCache | None = None


def series_cache(s: Settings) -> SeriesCache:
  global _cache
  if _cache is None:
    _cache = SeriesCache(s.tsdb_series_cache)
  return _cache


def error(status: int, message: str, **extra) -> ORJSONResponse:
  return ORJSONResponse({"error": {"code": status, "message": message, **extra}}, status_code=status)


def require_key(x_api_key: str | None = Header(default=None), s: Settings = Depends(get_settings)):
  if s.tsdb_api_key and not hmac.compare_digest(x_api_key or "", s.tsdb_api_key):
    raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")


@router.post("/api/ingest", dependencies=[Depends(require_key)])
async def ingest(request: Request, details: bool = True, s: Settings = Depends(get_settings)):
  length = request.headers.get("content-length")
  if length and length.isdigit() and int(length) > s.tsdb_max_body:
    return error(413, f"body larger than {s.tsdb_max_body} bytes")

  if request.headers.get("content-type", "").startswith("multipart/form-data"):
    form = await request.form()
    f = form.get("file")
    if not isinstance(f, UploadFile):
      return error(400, "multipart upload needs a 'file' field")

    async def chunks():
      while c := await f.read(1 << 20):
        yield c
    source = chunks()
  else:
    source = request.stream()

  result = IngestResult()
  try:
    await ingest_stream(source, get_store(), s, series_cache(s), result)
  except BodyTooLarge:
    return error(413, f"body larger than {s.tsdb_max_body} bytes uncompressed; "
                 f"{result.success} points before the limit were stored", success=result.success)
  except Exception as e:  # storage unreachable or insert rejected
    log.exception("ingest failed")
    return error(503, f"storage error: {e.__class__.__name__}: {str(e)[:300]}",
                 success=result.success, failed=result.failed)

  body = {"success": result.success, "failed": result.failed}
  if details:
    body["errors"] = result.errors
  return ORJSONResponse(body, status_code=200 if result.failed == 0 else 400)


@router.post("/api/query", dependencies=[Depends(require_key)])
async def query(request: Request, s: Settings = Depends(get_settings)):
  try:
    req = QueryIn.model_validate_json(await request.body())
  except ValidationError as e:
    first = e.errors()[0]
    where = ".".join(str(x) for x in first["loc"])
    return error(400, f"invalid request: {where}: {first['msg']}")
  try:
    return ORJSONResponse(await run_query(get_store(), s, req))
  except QueryError as e:
    return error(400, str(e))


def _flag(v: str | None) -> bool:
  return v is not None and v.lower() in ("", "1", "true", "yes")


@router.get("/api/query", dependencies=[Depends(require_key)])
async def query_get(request: Request, s: Settings = Depends(get_settings)):
  """OpenTSDB URL form: ?start=1d-ago&end=now&m=avg:1h-max-nan:explicit_tags:in_bw{ip=...,intf=2}"""
  qp = request.query_params
  ms = qp.getlist("m")
  if not ms:
    return error(400, "missing m= parameter")
  if "start" not in qp:
    return error(400, "missing start= parameter")
  try:
    req = QueryIn(start=qp["start"], end=qp.get("end"), queries=[parse_m(m) for m in ms],
                  msResolution=_flag(qp.get("ms")), arrays=_flag(qp.get("arrays")),
                  showQuery=_flag(qp.get("show_query")),
                  dedup=qp.get("dedup", "true").lower() not in ("0", "false", "no"))
    return ORJSONResponse(await run_query(get_store(), s, req))
  except QueryError as e:
    return error(400, str(e))
  except ValidationError as e:
    return error(400, f"invalid request: {e.errors()[0]['msg']}")


@router.get("/api/health")
async def health():
  store = get_store()
  try:
    ok = await store.ping()
  except Exception:
    ok = False
  # `<backend>: ok` (e.g. "clickhouse": true) is kept for clients written before `storage` existed.
  return ORJSONResponse({"status": "ok" if ok else "degraded", "backend": store.name, "storage": ok,
                         store.name: ok}, status_code=200 if ok else 503)
