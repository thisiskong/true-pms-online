"""Interface change history (intf_rev: one row per oper/speed state interval)."""
from datetime import datetime
from typing import Any

from app import db
from app.queries.devices import DeviceFilters, _Where, build_where
from app.queries.models import IntfChange, human_speed, rec

CHANGE_COLS = """r.id, r.rev, r.device_id, r.ifindex, coalesce(i.ifname, r.ifname) AS ifname, i.ifalias,
  r.ifoper, r.ifspeed, r.first, r.lastseen"""


def to_change(r: Any) -> IntfChange:
  d = rec(r)
  d["speed_text"] = human_speed(d.get("ifspeed"))
  return IntfChange(**d)


async def list_changes(
  device_id: int | None = None, interface_id: str | None = None,
  since: datetime | None = None, limit: int = 50,
) -> dict[str, Any]:
  parts: list[str] = []
  args: list[Any] = []
  if device_id is not None:
    args.append(device_id)
    parts.append(f"r.device_id = ${len(args)}")
  if interface_id:
    args.append(interface_id)
    parts.append(f"r.id = ${len(args)}")
  if since is not None:
    args.append(since)
    parts.append(f"r.first >= ${len(args)}")
  if not parts:
    raise ValueError("device_id, interface_id or since is required")
  args.append(limit + 1)
  rows = await db.fetch(
    f"""SELECT {CHANGE_COLS}, d.name AS device_name, d.ip AS device_ip
    FROM intf_rev r
    LEFT JOIN intf i ON i.id = r.id
    LEFT JOIN device d ON d.id = r.device_id
    WHERE {" AND ".join(parts)}
    ORDER BY r.first DESC NULLS LAST, r.rev DESC LIMIT ${len(args)}""",
    *args,
  )
  return {"items": [to_change(r) for r in rows[:limit]], "truncated": len(rows) > limit}


# A change is an intf_rev row with rev > 1: the step from the previous interval (rev - 1) into this one.
# rev 1 is the first time the interface was seen, not a change. intf_rev is written by a once-a-day poll,
# so two changes are at least ~24 h apart and bounces faster than that are invisible.
async def list_unstable(
  since: datetime, f: DeviceFilters, min_changes: int = 2, limit: int = 50, offset: int = 0,
) -> dict[str, Any]:
  """Interfaces with at least min_changes state changes since `since`, most changes first."""
  w = build_where(f, _Where())
  n = len(w.args)
  rows = await db.fetch(
    f"""WITH ch AS (
      SELECT r.id, r.device_id, r.ifname, r.ifoper, r.ifspeed, r.first,
        p.rev IS NOT NULL AS has_prev, p.ifoper AS p_oper, p.ifspeed AS p_speed
      FROM intf_rev r
      LEFT JOIN intf_rev p ON p.id = r.id AND p.rev = r.rev - 1
      WHERE r.rev > 1 AND r.first >= ${n + 1}
    ), g AS (
      SELECT ch.id, max(ch.device_id) AS device_id, max(ch.ifname) AS rev_ifname, count(*) AS changes,
        count(*) FILTER (WHERE NOT has_prev OR p_oper IS DISTINCT FROM ch.ifoper) AS oper_changes,
        count(*) FILTER (WHERE (NOT has_prev OR p_oper IS DISTINCT FROM ch.ifoper) AND ch.ifoper <> 'up') AS down_changes,
        count(*) FILTER (WHERE has_prev AND p_speed IS DISTINCT FROM ch.ifspeed) AS speed_changes,
        max(ch.first) AS last_change
      FROM ch JOIN device d ON d.id = ch.device_id
      {w.sql}
      GROUP BY ch.id HAVING count(*) >= ${n + 2}
    )
    SELECT g.id, g.device_id, g.changes, g.oper_changes, g.down_changes, g.speed_changes, g.last_change,
      coalesce(i.ifname, g.rev_ifname) AS ifname, i.ifalias, i.ifoper, i.ifadmin, i.ifspeed,
      d.name AS device_name, d.ip AS device_ip, d.vendor, d.model, d.topology, d.region, d.province, d.sitename,
      count(*) OVER () AS total
    FROM g JOIN device d ON d.id = g.device_id LEFT JOIN intf i ON i.id = g.id
    ORDER BY g.changes DESC, g.last_change DESC, g.id LIMIT ${n + 3} OFFSET ${n + 4}""",
    *w.args, since, min_changes, limit, offset,
  )
  items = []
  for r in rows:
    d = rec(r)
    d.pop("total")
    d["speed_text"] = human_speed(d.get("ifspeed"))
    items.append(d)
  if rows:
    total = rows[0]["total"]
  elif offset:  # past the last page: count separately
    total = (await list_unstable(since, f, min_changes, 1, 0))["total"]
  else:
    total = 0
  return {"items": items, "total": total, "truncated": total > offset + len(items)}


async def top_flapping(since: datetime, f: DeviceFilters, limit: int = 20) -> dict[str, Any]:
  r = await list_unstable(since, f, 1, limit)
  return {"items": r["items"], "total": r["total"], "truncated": r["truncated"]}
