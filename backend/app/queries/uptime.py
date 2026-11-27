"""Uptime / reachability queries (device_uptime joined to device on ip)."""
from datetime import datetime, timedelta
from typing import Any

from app import db
from app.queries.devices import ROW_COLS, UPTIME_COLS, DeviceFilters, _Where, build_where, to_row, uptime_from
from app.queries.models import Uptime, now_bkk_naive, rec


async def get_uptime(device_id: int) -> Uptime | None:
  r = await db.fetchrow(
    f"""SELECT {UPTIME_COLS} FROM device d JOIN device_uptime u ON u.ip = d.ip WHERE d.id = $1""",
    device_id,
  )
  return uptime_from(rec(r)) if r else None


async def _device_uptime_list(where_sql: str, args: list[Any], order: str, limit: int, offset: int = 0) -> dict[str, Any]:
  n = len(args)
  rows = await db.fetch(
    f"""SELECT {ROW_COLS}, {UPTIME_COLS}
    FROM device_uptime u JOIN device d ON d.ip = u.ip
    {where_sql} ORDER BY {order}, d.id LIMIT ${n + 1} OFFSET ${n + 2}""",
    *args, limit + 1, offset,
  )
  items = []
  for r in rows[:limit]:
    d = rec(r)
    up = uptime_from(d)
    row = to_row_dict(d)
    row["uptime"] = up.model_dump(mode="json") if up else None
    items.append(row)
  total = await db.fetchval(f"SELECT count(*) FROM device_uptime u JOIN device d ON d.ip = u.ip {where_sql}", *args)
  return {"items": items, "total": total, "truncated": total > offset + len(items)}


def to_row_dict(d: dict[str, Any]) -> dict[str, Any]:
  return to_row(d).model_dump(mode="json")


async def list_recent_reboots(since: datetime, f: DeviceFilters, limit: int = 50, offset: int = 0) -> dict[str, Any]:
  w = build_where(f, _Where())
  w.add("u.last_reboot_at >= ?", since)
  return await _device_uptime_list(w.sql, w.args, "u.last_reboot_at DESC", limit, offset)


async def list_unreachable(
  not_seen_for_hours: int, f: DeviceFilters, limit: int = 50, offset: int = 0, include_never: bool = True,
) -> dict[str, Any]:
  """Devices whose last successful ping is older than the cutoff. include_never adds devices that never answered
  (often misconfigured rather than down); they sort first."""
  cutoff = now_bkk_naive() - timedelta(hours=not_seen_for_hours)
  w = build_where(f, _Where())
  if include_never:
    w.add("(u.last_ping_success_at IS NULL OR u.last_ping_success_at < ?)", cutoff)
  else:
    w.add("u.last_ping_success_at < ?", cutoff)
  return await _device_uptime_list(w.sql, w.args, "u.last_ping_success_at ASC NULLS FIRST", limit, offset)
