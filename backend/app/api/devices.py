import csv
import io
from datetime import datetime
from typing import Annotated, Any, AsyncIterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.queries import changes, devices, interfaces, ponports, uptime
from app.queries.devices import DeviceFilters
from app.queries.models import (
  BKK, Device, DeviceRow, Interface, InterfaceSummary, IntfChange, Onu, Page, PonPort, Uptime, now_bkk_naive,
)
from datetime import timedelta

router = APIRouter(prefix="/api/devices", tags=["devices"])

EXPORT_CAP = 100_000

DeviceSort = Literal["name", "ip", "vendor", "model", "network", "topology", "region", "province", "sitename", "first", "lastseen", "pollstatus", "id"]
IntfSort = Literal["ifindex", "ifname", "ifalias", "ifoper", "ifadmin", "ifspeed", "iftype", "dstname", "lastseen"]
Order = Literal["asc", "desc"]


def device_filters(
  q: Annotated[str | None, Query(max_length=100)] = None,
  vendor: str | None = None,
  model: str | None = None,
  network: str | None = None,
  topology: str | None = None,
  region: str | None = None,
  province: str | None = None,
  sitename: str | None = None,
  pollstatus: Literal["Enable", "Disable"] | None = None,
  seen_within_days: Annotated[int | None, Query(ge=1, le=3650)] = None,
) -> DeviceFilters:
  return DeviceFilters(
    q=q or None, vendor=vendor or None, model=model or None, network=network or None,
    topology=topology or None, region=region or None, province=province or None,
    sitename=sitename or None, pollstatus=pollstatus, seen_within_days=seen_within_days,
  )


@router.get("", response_model=Page[DeviceRow])
async def list_devices(
  f: Annotated[DeviceFilters, Depends(device_filters)],
  page: Annotated[int, Query(ge=1, le=100000)] = 1,
  size: Annotated[int, Query(ge=1, le=200)] = 50,
  sort: DeviceSort = "name",
  order: Order = "asc",
) -> Page[DeviceRow]:
  return await devices.list_devices(f, page, size, sort, order)


@router.get("/facets")
async def facets(f: Annotated[DeviceFilters, Depends(device_filters)]) -> dict[str, list[dict[str, Any]]]:
  """Value counts for each filter dropdown, narrowed by all other active filters (not by its own)."""
  return await devices.all_facets(f)


CSV_COLS = ["id", "name", "ip", "vendor", "model", "network", "topology", "region", "province", "sitename", "pollstatus", "first", "lastseen"]


def _fmt(v: Any) -> Any:
  if isinstance(v, datetime):
    return v.strftime("%Y-%m-%d %H:%M:%S")
  return "" if v is None else v


@router.get("/export.csv")
async def export_csv(
  f: Annotated[DeviceFilters, Depends(device_filters)],
  sort: DeviceSort = "name",
  order: Order = "asc",
) -> StreamingResponse:
  async def gen() -> AsyncIterator[str]:
    buf = io.StringIO()
    w = csv.writer(buf)
    buf.write("﻿")  # BOM so Excel opens UTF-8 (Thai names) correctly
    w.writerow(CSV_COLS)
    n = 0
    async for row in devices.iter_devices_csv_rows(f, sort, order, EXPORT_CAP):
      d = row.model_dump()
      w.writerow([_fmt(d[c]) for c in CSV_COLS])
      n += 1
      if n % 1000 == 0:
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()
    yield buf.getvalue()

  stamp = datetime.now(BKK).strftime("%Y%m%d-%H%M")
  return StreamingResponse(
    gen(), media_type="text/csv; charset=utf-8",
    headers={"Content-Disposition": f'attachment; filename="devices-{stamp}.csv"'},
  )


@router.get("/{device_id}", response_model=Device)
async def get_device(device_id: int) -> Device:
  d = await devices.get_device(device_id)
  if d is None:
    raise HTTPException(404, "device not found")
  return d


@router.get("/{device_id}/uptime", response_model=Uptime | None)
async def get_uptime(device_id: int) -> Uptime | None:
  return await uptime.get_uptime(device_id)


@router.get("/{device_id}/interfaces/summary", response_model=InterfaceSummary)
async def interface_summary(device_id: int) -> InterfaceSummary:
  return await interfaces.interface_summary(device_id)


@router.get("/{device_id}/interfaces", response_model=Page[Interface])
async def list_interfaces(
  device_id: int,
  page: Annotated[int, Query(ge=1)] = 1,
  size: Annotated[int, Query(ge=1, le=500)] = 50,
  sort: IntfSort = "ifindex",
  order: Order = "asc",
  oper: str | None = None,
  q: Annotated[str | None, Query(max_length=100)] = None,
  has_neighbor: bool | None = None,
) -> Page[Interface]:
  return await interfaces.list_interfaces(device_id, page, size, sort, order, oper or None, q or None, has_neighbor)


@router.get("/{device_id}/ponports")
async def list_ponports(device_id: int) -> dict[str, list[PonPort] | bool]:
  """All PON ports of an OLT (empty for other devices)."""
  return await ponports.list_ponports(device_id)


@router.get("/{device_id}/ponports/revisions")
async def list_ponport_revs(
  device_id: int,
  ponport_id: Annotated[str, Query(min_length=1, max_length=200)],
  limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> dict[str, list[IntfChange] | bool]:
  """State history of one PON port (ponport_rev), newest first."""
  return await ponports.list_ponport_revs(device_id, ponport_id, limit)


@router.get("/{device_id}/ponports/onus")
async def list_onus(
  device_id: int,
  ponport: Annotated[str, Query(min_length=1, max_length=100)],
) -> dict[str, list[Onu] | bool]:
  """Subscriber ONUs on one PON port (odn_onu), ordered by ONT id."""
  return await ponports.list_onus(device_id, ponport)


@router.get("/{device_id}/neighbors")
async def neighbors(device_id: int, limit: Annotated[int, Query(ge=1, le=500)] = 200) -> dict[str, Any]:
  return await interfaces.find_neighbors(device_id, limit)


@router.get("/{device_id}/changes")
async def list_changes(
  device_id: int,
  limit: Annotated[int, Query(ge=1, le=500)] = 100,
  since_days: Annotated[int | None, Query(ge=1, le=3650)] = None,
  interface_id: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, list[IntfChange] | bool]:
  since = now_bkk_naive() - timedelta(days=since_days) if since_days else None
  return await changes.list_changes(device_id=device_id, interface_id=interface_id or None, since=since, limit=limit)
