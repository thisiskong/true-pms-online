"""Fleet-wide network health lists: recent reboots and unreachable devices (device_uptime joined to device), and
unstable interfaces (intf_rev).

Only devices with uptime polling are covered (see /api/stats/overview -> uptime.with_uptime).
"""
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.devices import device_filters
from app.queries import changes, uptime
from app.queries.devices import DeviceFilters
from app.queries.models import now_bkk_naive

router = APIRouter(prefix="/api/network", tags=["network"])

Page = Annotated[int, Query(ge=1, le=100000)]
Size = Annotated[int, Query(ge=1, le=200)]


def _paged(r: dict[str, Any], page: int, size: int) -> dict[str, Any]:
  return {"items": r["items"], "total": r["total"], "page": page, "size": size}


@router.get("/reboots")
async def reboots(
  f: Annotated[DeviceFilters, Depends(device_filters)],
  since_hours: Annotated[int, Query(ge=1, le=720)] = 24,
  page: Page = 1,
  size: Size = 50,
) -> dict[str, Any]:
  """Devices that rebooted within the last since_hours, newest first."""
  since = now_bkk_naive() - timedelta(hours=since_hours)
  return _paged(await uptime.list_recent_reboots(since, f, size, (page - 1) * size), page, size)


@router.get("/unreachable")
async def unreachable(
  f: Annotated[DeviceFilters, Depends(device_filters)],
  not_seen_for_hours: Annotated[int, Query(ge=1, le=720)] = 24,
  include_never: bool = True,
  page: Page = 1,
  size: Size = 50,
) -> dict[str, Any]:
  """Devices with no successful ping for at least not_seen_for_hours (never-answered devices first)."""
  r = await uptime.list_unreachable(not_seen_for_hours, f, size, (page - 1) * size, include_never)
  return _paged(r, page, size)


@router.get("/unstable")
async def unstable(
  f: Annotated[DeviceFilters, Depends(device_filters)],
  since_hours: Annotated[int, Query(ge=1, le=2160)] = 168,
  min_changes: Annotated[int, Query(ge=1, le=100)] = 2,
  page: Page = 1,
  size: Size = 50,
) -> dict[str, Any]:
  """Interfaces with at least min_changes oper/speed changes within since_hours (max 90 days), most first.
  The history comes from a once-a-day poll, so changes are at least ~24 h apart."""
  since = now_bkk_naive() - timedelta(hours=since_hours)
  return _paged(await changes.list_unstable(since, f, min_changes, size, (page - 1) * size), page, size)
