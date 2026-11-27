"""PON port queries (tables: ponport, ponport_rev; always filtered by indexed device_id). OLTs only."""
from typing import Any

from app import db
from app.queries import optics
from app.queries.models import IntfChange, Onu, PonPort, human_speed, poll_status, rec

PON_COLS = """p.id, p.device_id, p.ponport, p.ifindex, p.ifname, p.ifalias, p.ifdescr, p.iftype, p.ifspeed,
  p.ifadmin, p.ifoper, p.ifconn, p.l1sp, p.l1_dl_max_bw, p.l1_ul_max_bw, p.dl_bw_remaining, p.ul_bw_remaining,
  p.moduleclass, p.vendorpn, p.usr_pollstatus, p.sys_pollstatus, p.first, p.lastseen"""

# Natural order of "0-0-2-13" / "1-1-1-15": compare as an integer array.
NATURAL = """string_to_array(nullif(trim(both ',' from regexp_replace(coalesce(p.ponport, p.ifname, ''), '[^0-9]+', ',', 'g')), ''), ',')::bigint[]"""

MAX_PORTS = 1000
MAX_REVS = 500
MAX_ONUS = 1000

# odn_onu is keyed by device NAME (not id) + ponport string, e.g. ('BKK37017GO0', '0-0-2-13').
DEV_NAME = "(SELECT d.name FROM device d WHERE d.id = $1)"


def to_ponport(r: Any, pn_table: dict[str, tuple[str, str]] | None = None) -> PonPort:
  d = rec(r)
  d.update(optics.optic_fields(d, pn_table or {}))
  d["pollstatus"] = poll_status(d.pop("usr_pollstatus"), d.pop("sys_pollstatus"))
  d["speed_text"] = human_speed(d.get("ifspeed"))
  return PonPort(**d)


async def list_ponports(device_id: int) -> dict[str, Any]:
  rows = await db.fetch(
    f"""SELECT {PON_COLS}, coalesce(o.n, 0) AS onu_count, o.cap AS onu_capacity
    FROM ponport p
    LEFT JOIN (SELECT o.ponport, count(*) AS n, max(o.splitratio) AS cap FROM odn_onu o WHERE o.device = {DEV_NAME} GROUP BY 1) o ON o.ponport = p.ponport
    WHERE p.device_id = $1 ORDER BY {NATURAL} NULLS LAST, p.id LIMIT $2""",
    device_id, MAX_PORTS + 1,
  )
  table = await optics.pn_table()
  return {"items": [to_ponport(r, table) for r in rows[:MAX_PORTS]], "truncated": len(rows) > MAX_PORTS}


async def list_ponport_revs(device_id: int, ponport_id: str, limit: int = MAX_REVS) -> dict[str, Any]:
  rows = await db.fetch(
    """SELECT r.id, r.rev, r.device_id, r.ifindex, r.ifname, NULL::varchar AS ifalias,
      r.ifoper, r.ifspeed, r.first, r.lastseen
    FROM ponport_rev r
    WHERE r.device_id = $1 AND r.id = $2
    ORDER BY r.first DESC NULLS LAST, r.rev DESC LIMIT $3""",
    device_id, ponport_id, limit + 1,
  )
  items = []
  for r in rows[:limit]:
    d = rec(r)
    d["speed_text"] = human_speed(d.get("ifspeed"))
    items.append(IntfChange(**d))
  return {"items": items, "truncated": len(rows) > limit}


async def list_onus(device_id: int, ponport: str, limit: int = MAX_ONUS) -> dict[str, Any]:
  rows = await db.fetch(
    f"""SELECT o.ontid, o.accessid, o.devicesn, o.l1name, o.l2name, o.l1ratio, o.l2ratio, o.splitratio,
      o.l1len, o.l2len, o.dropwire, o.ranging, o.ranging_exclude, o.vendor, o.model, o.moduleclass, o.l2date, o.hsidate
    FROM odn_onu o
    WHERE o.device = {DEV_NAME} AND o.ponport = $2
    ORDER BY nullif(regexp_replace(o.ontid, '\\D', '', 'g'), '')::numeric NULLS LAST, o.ontid LIMIT $3""",
    device_id, ponport, limit + 1,
  )
  return {"items": [Onu(**rec(r)) for r in rows[:limit]], "truncated": len(rows) > limit}
