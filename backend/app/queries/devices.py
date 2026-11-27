"""Device inventory queries (table: device, LEFT JOIN device_uptime on ip).

The SNMP `community` column is never selected.
"""
import asyncio
from datetime import timedelta
from typing import Any, AsyncIterator, Literal

from pydantic import BaseModel, Field

from app import db
from app.cache import ttl_cache
from app.queries.models import (
  Device, DeviceRow, Page, Uptime, human_duration, now_bkk_naive, poll_status, rec,
)

FACET_FIELDS = ("vendor", "model", "network", "topology", "region", "province")
FacetField = Literal["vendor", "model", "network", "topology", "region", "province"]

POLL_EXPR = "coalesce(d.usr_pollstatus, d.sys_pollstatus)"

SORTS = {
  "name": "d.name", "ip": "d.ip", "vendor": "d.vendor", "model": "d.model",
  "network": "d.network", "topology": "d.topology", "region": "d.region",
  "province": "d.province", "sitename": "d.sitename", "first": "d.first",
  "lastseen": "d.lastseen", "pollstatus": POLL_EXPR, "id": "d.id",
}

ROW_COLS = """d.id, d.name, d.ip, d.vendor, d.model, d.network, d.topology, d.region,
  d.province, d.sitename, d.first, d.lastseen, d.usr_pollstatus, d.sys_pollstatus"""

DETAIL_COLS = """d.id, d.name, d.ip, d.chassisid, d.descr, d.vendor, d.model, d.swversion, d.olttype,
  d.network, d.topology, d.region, d.province, d.sitename, d.latitude, d.longitude,
  d.rn, d.pn, d.dn, d.ringid, d.ringtopo, d.hop,
  d.uplink_ip1, d.uplink_site1, d.uplink_model1, d.uplink_ip2, d.uplink_site2, d.uplink_model2,
  d.a_homing_id, d.a_homing_site, d.b_homing_id, d.b_homing_site, d.c_homing_id, d.c_homing_site,
  d.agent, d.pollint, d.usr_pollstatus, d.sys_pollstatus, d.first, d.lastseen,
  d.last_modify_at, d.last_modify_by"""

UPTIME_COLS = """u.ip AS u_ip, u.polled_at AS u_polled_at, u.poll_method AS u_poll_method,
  u.uptime AS u_uptime, u.last_reboot_at AS u_last_reboot_at,
  u.last_ping_success_at AS u_last_ping_success_at, u.last_ping_rtt_ms AS u_last_ping_rtt_ms"""


class DeviceFilters(BaseModel):
  q: str | None = Field(None, max_length=100, description="Substring of device name, site name, or IP prefix")
  vendor: str | None = Field(None, max_length=50)
  model: str | None = Field(None, max_length=80)
  network: str | None = Field(None, max_length=50)
  topology: str | None = Field(None, max_length=50)
  region: str | None = Field(None, max_length=50)
  province: str | None = Field(None, max_length=80)
  sitename: str | None = Field(None, max_length=80)
  pollstatus: Literal["Enable", "Disable"] | None = None
  seen_within_days: int | None = Field(None, ge=1, le=3650)


class _Where:
  def __init__(self) -> None:
    self.parts: list[str] = []
    self.args: list[Any] = []

  def add(self, sql: str, *vals: Any) -> None:
    for v in vals:
      self.args.append(v)
      sql = sql.replace("?", f"${len(self.args)}", 1)
    self.parts.append(sql)

  @property
  def sql(self) -> str:
    return ("WHERE " + " AND ".join(self.parts)) if self.parts else ""


def _escape_like(s: str) -> str:
  return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_where(f: DeviceFilters, w: _Where | None = None) -> _Where:
  w = w or _Where()
  if f.q:
    q = _escape_like(f.q.strip())
    w.add("(d.name ILIKE ? OR d.sitename ILIKE ? OR d.ip LIKE ?)", f"%{q}%", f"%{q}%", f"{q}%")
  for col in ("vendor", "model", "network", "topology", "region", "province", "sitename"):
    v = getattr(f, col)
    if v:
      w.add(f"d.{col} = ?", v)
  if f.pollstatus:
    w.add(f"{POLL_EXPR} = ?", 1 if f.pollstatus == "Enable" else 0)
  if f.seen_within_days:
    w.add("d.lastseen >= ?", now_bkk_naive() - timedelta(days=f.seen_within_days))
  return w


def to_row(r: Any) -> DeviceRow:
  d = rec(r)
  d["pollstatus"] = poll_status(d.pop("usr_pollstatus"), d.pop("sys_pollstatus"))
  return DeviceRow(**d)


def uptime_from(d: dict[str, Any]) -> Uptime | None:
  """Pop u_* columns from a joined row and build an Uptime (or None)."""
  u = {k[2:]: d.pop(k) for k in list(d) if k.startswith("u_")}
  if not u.get("ip"):
    return None
  td = u.pop("uptime")
  return Uptime(
    **u,
    uptime_seconds=int(td.total_seconds()) if td is not None else None,
    uptime_text=human_duration(td),
  )


@ttl_cache(60)
async def _count_all() -> int:
  return await db.fetchval("SELECT count(*) FROM device")


async def list_devices(
  f: DeviceFilters, page: int = 1, size: int = 50, sort: str = "name", order: str = "asc",
) -> Page[DeviceRow]:
  w = build_where(f)
  sort_sql = SORTS.get(sort, "d.name")
  order_sql = "DESC" if order.lower() == "desc" else "ASC"
  offset = (page - 1) * size
  n = len(w.args)
  rows = await db.fetch(
    f"""SELECT {ROW_COLS} FROM device d {w.sql}
    ORDER BY {sort_sql} {order_sql} NULLS LAST, d.id
    LIMIT ${n + 1} OFFSET ${n + 2}""",
    *w.args, size, offset,
  )
  total = await (_count_all() if not w.parts else db.fetchval(f"SELECT count(*) FROM device d {w.sql}", *w.args))
  return Page[DeviceRow](items=[to_row(r) for r in rows], page=page, size=size, total=total)


async def iter_devices_csv_rows(f: DeviceFilters, sort: str, order: str, cap: int) -> AsyncIterator[DeviceRow]:
  w = build_where(f)
  sort_sql = SORTS.get(sort, "d.name")
  order_sql = "DESC" if order.lower() == "desc" else "ASC"
  sql = f"""SELECT {ROW_COLS} FROM device d {w.sql}
    ORDER BY {sort_sql} {order_sql} NULLS LAST, d.id LIMIT {int(cap)}"""
  async with db.readonly_cursor(sql, *w.args) as cur:
    async for r in cur:
      yield to_row(r)


async def get_device(device_id: int) -> Device | None:
  r = await db.fetchrow(
    f"""SELECT {DETAIL_COLS}, {UPTIME_COLS}
    FROM device d LEFT JOIN device_uptime u ON u.ip = d.ip
    WHERE d.id = $1""",
    device_id,
  )
  if r is None:
    return None
  d = rec(r)
  up = uptime_from(d)
  d["pollstatus"] = poll_status(d.pop("usr_pollstatus"), d.pop("sys_pollstatus"))
  return Device(**d, uptime=up)


async def find_devices_by_key(name: str | None = None, ip: str | None = None, limit: int = 10) -> list[DeviceRow]:
  """Exact (case-insensitive) match on name, or exact match on IP."""
  if ip:
    rows = await db.fetch(f"SELECT {ROW_COLS} FROM device d WHERE d.ip = $1 ORDER BY d.lastseen DESC NULLS LAST LIMIT $2", ip.strip(), limit)
  elif name:
    rows = await db.fetch(f"SELECT {ROW_COLS} FROM device d WHERE lower(d.name) = lower($1) ORDER BY d.lastseen DESC NULLS LAST LIMIT $2", name.strip(), limit)
  else:
    return []
  return [to_row(r) for r in rows]


async def count_devices(f: DeviceFilters, group_by: str | None = None, limit: int = 50) -> dict[str, Any]:
  w = build_where(f)
  if not group_by:
    total = await db.fetchval(f"SELECT count(*) FROM device d {w.sql}", *w.args)
    return {"total": total}
  expr = SORTS[group_by] if group_by in SORTS else None
  if expr is None:
    raise ValueError(f"cannot group by {group_by}")
  n = len(w.args)
  rows = await db.fetch(
    f"""SELECT {expr} AS k, count(*) AS c FROM device d {w.sql}
    GROUP BY 1 ORDER BY 2 DESC LIMIT ${n + 1}""",
    *w.args, limit,
  )
  total = await db.fetchval(f"SELECT count(*) FROM device d {w.sql}", *w.args)
  groups = []
  for r in rows:
    k = r["k"]
    if group_by == "pollstatus":
      k = poll_status(None, k)
    groups.append({"value": k, "count": r["c"]})
  return {"total": total, "group_by": group_by, "groups": groups, "truncated": len(rows) >= limit}


@ttl_cache(900)
async def facet_values(field: str) -> list[dict[str, Any]]:
  if field not in FACET_FIELDS:
    raise ValueError(f"unknown facet {field}")
  rows = await db.fetch(
    f"SELECT {field} AS v, count(*) AS c FROM device WHERE {field} IS NOT NULL AND {field} <> '' GROUP BY 1 ORDER BY 2 DESC LIMIT 500"
  )
  return [{"value": r["v"], "count": r["c"]} for r in rows]


async def _facet_counts(f: DeviceFilters, field: str) -> list[dict[str, Any]]:
  """Counts per value of `field` under every active filter EXCEPT the one on `field` itself."""
  w = build_where(f.model_copy(update={field: None}))
  if field == "pollstatus":
    expr = POLL_EXPR
    w.add(f"{POLL_EXPR} IS NOT NULL")
  else:
    expr = f"d.{field}"
    w.add(f"d.{field} IS NOT NULL AND d.{field} <> ''")
  rows = await db.fetch(f"SELECT {expr} AS v, count(*) AS c FROM device d {w.sql} GROUP BY 1 ORDER BY 2 DESC LIMIT 500", *w.args)
  if field == "pollstatus":
    return [{"value": poll_status(None, r["v"]), "count": r["c"]} for r in rows]
  return [{"value": r["v"], "count": r["c"]} for r in rows]


@ttl_cache(60)
async def _filtered_facets(filters_json: str) -> dict[str, list[dict[str, Any]]]:
  f = DeviceFilters.model_validate_json(filters_json)
  fields = (*FACET_FIELDS, "pollstatus")
  results = await asyncio.gather(*(_facet_counts(f, fld) for fld in fields))
  return dict(zip(fields, results))


async def all_facets(f: DeviceFilters | None = None) -> dict[str, list[dict[str, Any]]]:
  """Facet counts for the filter dropdowns, narrowed by the other active filters."""
  f = f or DeviceFilters()
  return await _filtered_facets(f.model_dump_json(exclude_none=True))
