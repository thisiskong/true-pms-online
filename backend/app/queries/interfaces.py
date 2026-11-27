"""Interface queries (table: intf, always filtered by indexed device_id)."""
from typing import Any

from app import db
from app.queries.devices import _escape_like
from app.queries.models import (
  Interface, InterfaceSummary, Neighbor, Page, human_speed, poll_status, rec,
)

INTF_COLS = """i.id, i.device_id, i.ifindex, i.ifname, i.ifalias, i.ifdescr, i.iftype, i.ifspeed,
  i.ifadmin, i.ifoper, i.ifphyaddr, i.dstname, i.dstport, i.dstsite, i.dsttype, i.mediatype,
  i.vendorpn, i.moduleclass, i.usr_pollstatus, i.sys_pollstatus, i.first, i.lastseen"""

SORTS = {
  "ifname": "i.ifname", "ifalias": "i.ifalias", "ifoper": "i.ifoper", "ifadmin": "i.ifadmin",
  "ifspeed": "i.ifspeed", "iftype": "i.iftype", "dstname": "i.dstname", "lastseen": "i.lastseen",
  "ifindex": "nullif(regexp_replace(i.ifindex, '\\D', '', 'g'), '')::numeric",
}

SPEED_BUCKET = """CASE
  WHEN i.ifspeed IS NULL OR i.ifspeed = 0 THEN '0 / unknown'
  WHEN i.ifspeed < 1000000000 THEN '< 1G'
  WHEN i.ifspeed < 10000000000 THEN '1G'
  WHEN i.ifspeed < 25000000000 THEN '10G'
  WHEN i.ifspeed < 100000000000 THEN '25G-40G'
  WHEN i.ifspeed < 400000000000 THEN '100G'
  ELSE '400G+' END"""


def to_intf(r: Any) -> Interface:
  d = rec(r)
  d["pollstatus"] = poll_status(d.pop("usr_pollstatus"), d.pop("sys_pollstatus"))
  d["speed_text"] = human_speed(d.get("ifspeed"))
  return Interface(**d)


def _where(device_id: int, oper: str | None, q: str | None, has_neighbor: bool | None) -> tuple[str, list[Any]]:
  parts = ["i.device_id = $1"]
  args: list[Any] = [device_id]
  if oper:
    args.append(oper)
    parts.append(f"i.ifoper = ${len(args)}")
  if q:
    args.append(f"%{_escape_like(q.strip())}%")
    parts.append(f"(i.ifname ILIKE ${len(args)} OR i.ifalias ILIKE ${len(args)} OR i.dstname ILIKE ${len(args)})")
  if has_neighbor is True:
    parts.append("coalesce(i.dstname, '') <> ''")
  elif has_neighbor is False:
    parts.append("coalesce(i.dstname, '') = ''")
  return "WHERE " + " AND ".join(parts), args


async def list_interfaces(
  device_id: int, page: int = 1, size: int = 50, sort: str = "ifindex", order: str = "asc",
  oper: str | None = None, q: str | None = None, has_neighbor: bool | None = None,
) -> Page[Interface]:
  where, args = _where(device_id, oper, q, has_neighbor)
  sort_sql = SORTS.get(sort, SORTS["ifindex"])
  order_sql = "DESC" if order.lower() == "desc" else "ASC"
  n = len(args)
  rows = await db.fetch(
    f"""SELECT {INTF_COLS} FROM intf i {where}
    ORDER BY {sort_sql} {order_sql} NULLS LAST, i.id LIMIT ${n + 1} OFFSET ${n + 2}""",
    *args, size, (page - 1) * size,
  )
  total = await db.fetchval(f"SELECT count(*) FROM intf i {where}", *args)
  return Page[Interface](items=[to_intf(r) for r in rows], page=page, size=size, total=total)


async def get_interface(interface_id: str | None = None, device_id: int | None = None, ifname: str | None = None) -> Interface | None:
  if interface_id:
    r = await db.fetchrow(f"SELECT {INTF_COLS} FROM intf i WHERE i.id = $1", interface_id)
  elif device_id is not None and ifname:
    r = await db.fetchrow(
      f"SELECT {INTF_COLS} FROM intf i WHERE i.device_id = $1 AND lower(i.ifname) = lower($2) LIMIT 1",
      device_id, ifname.strip(),
    )
  else:
    return None
  return to_intf(r) if r else None


async def interface_summary(device_id: int) -> InterfaceSummary:
  rows = await db.fetch(
    f"""SELECT 'oper' AS dim, coalesce(i.ifoper, 'unknown') AS k, count(*) AS c FROM intf i WHERE i.device_id = $1 GROUP BY 2
    UNION ALL SELECT 'admin', coalesce(i.ifadmin, 'unknown'), count(*) FROM intf i WHERE i.device_id = $1 GROUP BY 2
    UNION ALL SELECT 'speed', {SPEED_BUCKET}, count(*) FROM intf i WHERE i.device_id = $1 GROUP BY 2
    UNION ALL SELECT 'type', coalesce(i.iftype, 'unknown'), count(*) FROM intf i WHERE i.device_id = $1 GROUP BY 2
    UNION ALL SELECT 'nbr', 'with_neighbor', count(*) FROM intf i WHERE i.device_id = $1 AND coalesce(i.dstname, '') <> ''""",
    device_id,
  )
  dims: dict[str, dict[str, int]] = {"oper": {}, "admin": {}, "speed": {}, "type": {}, "nbr": {}}
  for r in rows:
    dims[r["dim"]][r["k"]] = r["c"]
  by_type = dict(sorted(dims["type"].items(), key=lambda kv: -kv[1])[:15])
  return InterfaceSummary(
    device_id=device_id,
    total=sum(dims["oper"].values()),
    by_oper=dims["oper"],
    by_admin=dims["admin"],
    by_speed=dims["speed"],
    by_type=by_type,
    with_neighbor=dims["nbr"].get("with_neighbor", 0),
  )


async def find_neighbors(device_id: int, limit: int = 100) -> dict[str, Any]:
  """LLDP neighbors; matched to a known device when the neighbor's sysName equals device.name."""
  rows = await db.fetch(
    """SELECT i.ifname, i.ifalias, i.ifoper, i.dstname, i.dstport, i.dstsite,
      nd.id AS neighbor_device_id, nd.ip AS neighbor_ip
    FROM intf i
    LEFT JOIN LATERAL (
      SELECT d.id, d.ip FROM device d WHERE d.name = i.dstname ORDER BY d.lastseen DESC NULLS LAST LIMIT 1
    ) nd ON true
    WHERE i.device_id = $1 AND coalesce(i.dstname, '') <> ''
    ORDER BY i.ifname LIMIT $2""",
    device_id, limit + 1,
  )
  items = [Neighbor(**rec(r)).model_dump(mode="json") for r in rows[:limit]]
  return {"items": items, "truncated": len(rows) > limit}
