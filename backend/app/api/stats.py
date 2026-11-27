from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app import db
from app.config import get_settings
from app.api.devices import device_filters
from app.queries import stats
from app.queries.devices import DeviceFilters

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats/overview")
async def overview() -> dict[str, Any]:
  return await stats.fleet_overview()


@router.get("/stats/kpis")
async def kpis(f: Annotated[DeviceFilters, Depends(device_filters)]) -> dict[str, Any]:
  """KPI cards for the device list, over the devices matching the given filters."""
  return await stats.kpis(f)


@router.get("/health")
async def health() -> dict[str, Any]:
  try:
    ok = await db.fetchval("SELECT 1") == 1
  except Exception:
    ok = False
  return {"status": "ok" if ok else "degraded", "db": ok}


@router.get("/meta")
async def meta() -> dict[str, Any]:
  s = get_settings()
  return {"chat_provider": s.llm_provider, "chat_model": s.active_chat_model, "chat_configured": s.chat_configured}
