"""Fleet-wide aggregates (cached; some scan the 2.8M-row intf table)."""
import asyncio
from datetime import timedelta
from typing import Any

from app import db
from app.cache import ttl_cache
from app.queries.devices import DeviceFilters, _Where, build_where
from app.queries.models import now_bkk_naive, poll_status


async def _group(sql: str, *args: Any) -> list[dict[str, Any]]:
  return [{"value": r["k"], "count": r["c"]} for r in await db.fetch(sql, *args)]


@ttl_cache(60)
async def _filtered_kpis(filters_json: str) -> dict[str, Any]:
  f = DeviceFilters.model_validate_json(filters_json)
  now = now_bkk_naive()
  day, week = now - timedelta(hours=24), now - timedelta(days=7)

  async def devices() -> int:
    w = build_where(f)
    return await db.fetchval(f"SELECT count(*) FROM device d {w.sql}", *w.args)

  async def uptime() -> dict[str, Any]:
    w = build_where(f, _Where())
    n = len(w.args)
    r = await db.fetchrow(
      f"""SELECT count(*) AS with_uptime,
        count(*) FILTER (WHERE u.last_reboot_at >= ${n + 1}) AS rebooted_24h,
        count(*) FILTER (WHERE u.last_reboot_at >= ${n + 2}) AS rebooted_7d,
        count(*) FILTER (WHERE u.last_ping_success_at IS NULL OR u.last_ping_success_at < ${n + 1}) AS unreachable_24h
      FROM device d JOIN device_uptime u ON u.ip = d.ip {w.sql}""",
      *w.args, day, week,
    )
    return dict(r) if r else {}

  async def changes() -> int:
    w = build_where(f, _Where())
    w.add("r.first >= ?", day)
    return await db.fetchval(f"SELECT count(*) FROM intf_rev r JOIN device d ON d.id = r.device_id {w.sql}", *w.args)

  n_dev, up, ch = await asyncio.gather(devices(), uptime(), changes())
  return {
    "generated_at": now.isoformat() + "+07:00",
    "filtered": bool(f.model_dump(exclude_none=True)),
    "devices": n_dev,
    "uptime": up,
    "interface_changes_24h": ch,
  }


async def kpis(f: DeviceFilters | None = None) -> dict[str, Any]:
  """Device-list KPI cards, computed over the devices matching the active filters."""
  return await _filtered_kpis((f or DeviceFilters()).model_dump_json(exclude_none=True))


@ttl_cache(300)
async def fleet_overview() -> dict[str, Any]:
  now = now_bkk_naive()
  devices = await db.fetchval("SELECT count(*) FROM device")
  by_network = await _group("SELECT network AS k, count(*) AS c FROM device GROUP BY 1 ORDER BY 2 DESC LIMIT 20")
  by_topology = await _group("SELECT topology AS k, count(*) AS c FROM device GROUP BY 1 ORDER BY 2 DESC LIMIT 20")
  by_vendor = await _group("SELECT vendor AS k, count(*) AS c FROM device GROUP BY 1 ORDER BY 2 DESC LIMIT 20")
  by_poll = await _group(
    "SELECT coalesce(usr_pollstatus, sys_pollstatus) AS k, count(*) AS c FROM device GROUP BY 1 ORDER BY 2 DESC"
  )
  for g in by_poll:
    g["value"] = poll_status(None, g["value"])
  up = await db.fetchrow(
    """SELECT count(*) AS with_uptime,
      count(*) FILTER (WHERE u.last_reboot_at >= $1) AS rebooted_24h,
      count(*) FILTER (WHERE u.last_reboot_at >= $2) AS rebooted_7d,
      count(*) FILTER (WHERE u.last_ping_success_at IS NULL OR u.last_ping_success_at < $1) AS unreachable_24h
    FROM device d JOIN device_uptime u ON u.ip = d.ip""",
    now - timedelta(hours=24), now - timedelta(days=7),
  )
  intf_oper = await _group("SELECT coalesce(ifoper, 'unknown') AS k, count(*) AS c FROM intf GROUP BY 1 ORDER BY 2 DESC")
  changes_24h = await db.fetchval("SELECT count(*) FROM intf_rev WHERE first >= $1", now - timedelta(hours=24))
  return {
    "generated_at": now.isoformat() + "+07:00",
    "devices": devices,
    "by_network": by_network,
    "by_topology": by_topology,
    "by_vendor": by_vendor,
    "by_pollstatus": by_poll,
    "uptime": dict(up) if up else {},
    "interfaces": {"total": sum(g["count"] for g in intf_oper), "by_oper": intf_oper},
    "interface_changes_24h": changes_24h,
  }
