"""Read-only metadata endpoints for UIs: GET /api/suggest (OpenTSDB-style) and GET /api/stats."""
import time

from fastapi import APIRouter, Depends, Query

from ..config import Settings, get_settings
from ..store import get_store
from .routes import ORJSONResponse, error, require_key

router = APIRouter()

STATS_TTL_S = 30
_stats_cache: dict[str, tuple[float, dict]] = {}


@router.get("/api/suggest", dependencies=[Depends(require_key)])
async def suggest(type: str, q: str = "", max: int = Query(25, ge=1, le=1000),
                  metric: str | None = None, tagk: str | None = None):
  """Prefix autocomplete. `metric` (and `tagk` for tagv) narrow the result: an extension to OpenTSDB."""
  if type not in ("metrics", "tagk", "tagv"):
    return error(400, "type must be metrics, tagk or tagv")
  return ORJSONResponse(await get_store().suggest(type, q, max, metric, tagk))


@router.get("/api/stats", dependencies=[Depends(require_key)])
async def stats(s: Settings = Depends(get_settings)):
  """Storage overview plus per-metric series counts and recent activity. Cached for 30 s."""
  store = get_store()
  db = s.database
  hit = _stats_cache.get(db)
  if hit and time.monotonic() - hit[0] < STATS_TTL_S:
    return ORJSONResponse(hit[1])

  raw = await store.stats()
  per: dict[str, dict] = {}
  for m, n in raw["series"]:
    per[m] = {"metric": m, "series": int(n), "tag_keys": [], "rows_24h": 0, "last_ts": None, "last_ingest": None}
  for m, ks in raw["keys"]:
    if m in per:
      per[m]["tag_keys"] = sorted(ks)
  for m, n, last_ts, last_ing in raw["recent"]:
    if m in per:
      per[m].update(rows_24h=int(n), last_ts=int(last_ts), last_ingest=int(last_ing))

  metrics = sorted(per.values(), key=lambda r: r["metric"])
  ingests = [r["last_ingest"] for r in metrics if r["last_ingest"]]
  body = {
    "backend": store.name,
    "database": db,
    **{k: raw[k] for k in ("rows", "disk_bytes", "uncompressed_bytes", "parts", "days", "first_day", "last_day")},
    "series": sum(r["series"] for r in metrics),
    "last_ingest": max(ingests) if ingests else None,
    "metrics": metrics,
  }
  _stats_cache[db] = (time.monotonic(), body)
  return ORJSONResponse(body)
