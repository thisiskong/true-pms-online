"""Fleet-wide interface list (table: intf, ~2.8M rows, not limited to one device).

Indexes on intf: id, device_id, device_ip, ifname, ifalias, name, dstsite. To keep it fast:
- the default sort is `name` alone, which walks the name index (about 30 ms for a page);
- the device search is resolved against the small device table first, then hits intf by device_id;
- the free-text interface search (`q`) scans the whole table (2-3 s) unless a device or another filter narrows it.
"""
import asyncio
from typing import Any

from app import db
from app.cache import ttl_cache
from app.queries.devices import _escape_like
from app.queries.models import human_speed, rec

COLS = """i.id, i.device_id, i.device_name, i.device_ip, i.name, i.altname, i.ifspeed, i.ifoper,
  i.dsttype, i.dstsite, i.dstport, i.moduleclass, i.lastseen"""

SORTS = {
  "name": "i.name", "device_name": "i.device_name", "device_ip": "i.device_ip", "altname": "i.altname",
  "ifspeed": "i.ifspeed", "ifoper": "i.ifoper", "dsttype": "i.dsttype", "dstsite": "i.dstsite",
  "dstport": "i.dstport", "moduleclass": "i.moduleclass", "lastseen": "i.lastseen",
}


def _where(device: str | None, q: str | None, ifoper: str | None, dsttype: str | None, moduleclass: str | None) -> tuple[str, list[Any]]:
  parts: list[str] = []
  args: list[Any] = []

  def arg(v: Any) -> str:
    args.append(v)
    return f"${len(args)}"

  if device and device.strip():
    d = _escape_like(device.strip())
    parts.append(f"i.device_id = ANY(ARRAY(SELECT id FROM device WHERE name ILIKE {arg(f'%{d}%')} OR ip LIKE {arg(f'{d}%')}))")
  if q and q.strip():
    p = arg(f"%{_escape_like(q.strip())}%")
    parts.append(f"(i.name ILIKE {p} OR i.altname ILIKE {p} OR i.ifname ILIKE {p} OR i.ifalias ILIKE {p} OR i.dstsite ILIKE {p} OR i.dstport ILIKE {p})")
  for col, v in (("ifoper", ifoper), ("dsttype", dsttype), ("moduleclass", moduleclass)):
    if v == "(none)":
      parts.append(f"i.{col} IS NULL")
    elif v:
      parts.append(f"i.{col} = {arg(v)}")
  return ("WHERE " + " AND ".join(parts)) if parts else "", args


@ttl_cache(300)
async def _count_all() -> int:
  return await db.fetchval("SELECT count(*) FROM intf")


async def list_interfaces(
  device: str | None = None, q: str | None = None, ifoper: str | None = None, dsttype: str | None = None,
  moduleclass: str | None = None, sort: str = "name", order: str = "asc", page: int = 1, size: int = 50,
) -> dict[str, Any]:
  where, args = _where(device, q, ifoper, dsttype, moduleclass)
  direction = "DESC" if order.lower() == "desc" else "ASC"
  col = SORTS.get(sort, SORTS["name"])
  # `name` alone keeps the index scan; other sorts break ties by name.
  order_sql = f"{col} {direction}" if col == "i.name" else f"{col} {direction} NULLS LAST, i.name"
  n = len(args)
  rows_q = db.fetch(f"SELECT {COLS} FROM intf i {where} ORDER BY {order_sql} LIMIT ${n + 1} OFFSET ${n + 2}",
                    *args, size, (page - 1) * size)
  count_q = db.fetchval(f"SELECT count(*) FROM intf i {where}", *args) if where else _count_all()
  rows, total = await asyncio.gather(rows_q, count_q)
  items = []
  for r in rows:
    d = rec(r)
    d["speed_text"] = human_speed(d.get("ifspeed"))
    items.append(d)
  return {"items": items, "total": total, "page": page, "size": size}


@ttl_cache(3600)
async def facets() -> dict[str, list[dict[str, Any]]]:
  """Dropdown values with fleet-wide counts (NULL shown as "(none)"); moduleclass is limited to the 80 most common."""
  rows = await db.fetch(
    """SELECT 'ifoper' AS dim, coalesce(ifoper, '(none)') AS v, count(*) AS c FROM intf GROUP BY 2
    UNION ALL SELECT 'dsttype', coalesce(dsttype, '(none)'), count(*) FROM intf GROUP BY 2
    UNION ALL SELECT 'moduleclass', coalesce(moduleclass, '(none)'), count(*) FROM intf GROUP BY 2""")
  out: dict[str, list[dict[str, Any]]] = {"ifoper": [], "dsttype": [], "moduleclass": []}
  for r in sorted(rows, key=lambda r: -r["c"]):
    out[r["dim"]].append({"value": r["v"], "count": r["c"]})
  out["moduleclass"] = out["moduleclass"][:80]
  return out


# ---------- chat / MCP tools: fleet-wide interface search and counts ----------
# Device filters (topology, vendor, region, ...) are resolved to device ids first, so intf is reached through its
# device_id index: e.g. all OLT interfaces (~13.6k devices) take about a second, not a 2.8M-row scan.

from app.queries.devices import DeviceFilters, _Where, build_where  # noqa: E402
from app.queries.interfaces import SPEED_BUCKET  # noqa: E402

GROUPS = {
  "oper": "coalesce(i.ifoper, 'unknown')", "admin": "coalesce(i.ifadmin, 'unknown')", "speed": SPEED_BUCKET,
  "dsttype": "coalesce(i.dsttype, '(none)')", "moduleclass": "coalesce(i.moduleclass, '(none)')",
  "iftype": "coalesce(i.iftype, 'unknown')",
  "vendor": "coalesce(d.vendor, 'unknown')", "model": "coalesce(d.model, 'unknown')",
  "topology": "coalesce(d.topology, 'unknown')", "region": "coalesce(d.region, 'unknown')",
  "province": "coalesce(d.province, 'unknown')",
}  # "device" is handled separately (returns identity columns too)

TOOL_COLS = """i.id, i.device_id, d.name AS device_name, d.ip AS device_ip, d.topology, d.region, i.ifname, i.ifalias,
  i.ifspeed, i.ifadmin, i.ifoper, i.dsttype, i.dstsite, i.dstname, i.dstport, i.moduleclass, i.lastseen"""


def _fleet_where(
  f: DeviceFilters, oper: str | None = None, admin: str | None = None, dsttype: str | None = None,
  moduleclass: str | None = None, min_speed_mbps: int | None = None, max_speed_mbps: int | None = None,
  text: str | None = None, has_neighbor: bool | None = None,
) -> _Where:
  dw = build_where(f, _Where())
  w = _Where()
  if dw.parts:
    # Re-number the device filter's $n placeholders into this query.
    sql = " AND ".join(dw.parts)
    for k in range(len(dw.args), 0, -1):
      sql = sql.replace(f"${k}", f"__ARG{k}__")
    for k, v in enumerate(dw.args, 1):
      w.args.append(v)
      sql = sql.replace(f"__ARG{k}__", f"${len(w.args)}")
    w.parts.append(f"i.device_id = ANY(ARRAY(SELECT d.id FROM device d WHERE {sql}))")
  if oper:
    w.add("i.ifoper = ?", oper)
  if admin:
    w.add("i.ifadmin = ?", admin)
  if dsttype:
    w.add("i.dsttype = ?", dsttype)
  if moduleclass:
    w.add("i.moduleclass = ?", moduleclass)
  if min_speed_mbps is not None:
    w.add("i.ifspeed >= ?", min_speed_mbps * 1_000_000)
  if max_speed_mbps is not None:
    w.add("i.ifspeed <= ?", max_speed_mbps * 1_000_000)
  if text and text.strip():
    p = f"%{_escape_like(text.strip())}%"
    w.add("(i.ifname ILIKE ? OR i.ifalias ILIKE ? OR i.dstname ILIKE ? OR i.dstsite ILIKE ? OR i.dstport ILIKE ?)", p, p, p, p, p)
  if has_neighbor is True:
    w.parts.append("coalesce(i.dstname, '') <> ''")
  elif has_neighbor is False:
    w.parts.append("coalesce(i.dstname, '') = ''")
  return w


async def search_fleet(w: _Where, limit: int = 50) -> dict[str, Any]:
  n = len(w.args)
  rows, total = await asyncio.gather(
    db.fetch(f"""SELECT {TOOL_COLS} FROM intf i LEFT JOIN device d ON d.id = i.device_id {w.sql}
      ORDER BY d.name, i.ifname LIMIT ${n + 1}""", *w.args, limit),
    db.fetchval(f"SELECT count(*) FROM intf i {w.sql}", *w.args),
  )
  items = []
  for r in rows:
    d = rec(r)
    d["speed_text"] = human_speed(d.pop("ifspeed"))
    items.append(d)
  return {"items": items, "total": total, "truncated": total > len(items)}


async def count_fleet(w: _Where, group_by: str | None = None, limit: int = 50) -> dict[str, Any]:
  if not group_by:
    return {"total": await db.fetchval(f"SELECT count(*) FROM intf i {w.sql}", *w.args)}
  if group_by == "device":
    # Include the device's identity so the model does not need a follow-up lookup per device.
    rows = await db.fetch(
      f"""SELECT d.id, d.name, d.ip, d.vendor, d.model, d.topology, d.region, d.province, count(*) AS c,
        sum(count(*)) OVER () AS total, count(*) OVER () AS n_groups
      FROM intf i JOIN device d ON d.id = i.device_id {w.sql}
      GROUP BY d.id ORDER BY c DESC, d.name LIMIT ${len(w.args) + 1}""", *w.args, limit)
    return {
      "group_by": "device", "total": int(rows[0]["total"]) if rows else 0, "devices": rows[0]["n_groups"] if rows else 0,
      "groups": [{"device_id": r["id"], "value": r["name"], "ip": r["ip"], "vendor": r["vendor"], "model": r["model"],
                  "region": r["region"], "province": r["province"], "count": r["c"]} for r in rows],
      "truncated": bool(rows) and rows[0]["n_groups"] > len(rows),
    }
  key = GROUPS[group_by]
  join = "LEFT JOIN device d ON d.id = i.device_id" if "d." in key else ""
  rows = await db.fetch(
    f"""SELECT {key} AS k, count(*) AS c, sum(count(*)) OVER () AS total FROM intf i {join} {w.sql}
    GROUP BY 1 ORDER BY 2 DESC LIMIT ${len(w.args) + 1}""", *w.args, limit + 1)
  total = rows[0]["total"] if rows else 0
  return {
    "group_by": group_by, "total": int(total or 0),
    "groups": [{"value": r["k"], "count": r["c"]} for r in rows[:limit]], "truncated": len(rows) > limit,
  }
