"""Fleet-wide board (line card / control board) list. Table: board (~49k rows, only the id is indexed; small enough to scan)."""
import asyncio
from typing import Any

from app import db
from app.cache import ttl_cache
from app.queries.devices import _escape_like
from app.queries.models import rec

COLS = "b.id, b.device_id, b.device_name, b.device_ip, b.boardname, b.boardtype, b.boardrole, b.operstatus, b.first, b.lastseen"

SORTS = {k: f"b.{k}" for k in ("device_name", "device_ip", "boardname", "boardtype", "boardrole", "operstatus", "first", "lastseen")}
FACETS = ("boardtype", "boardrole", "operstatus")


def _where(device: str | None, q: str | None, filters: dict[str, str | None]) -> tuple[str, list[Any]]:
  parts: list[str] = []
  args: list[Any] = []

  def arg(v: Any) -> str:
    args.append(v)
    return f"${len(args)}"

  if device and device.strip():
    d = _escape_like(device.strip())
    parts.append(f"(b.device_name ILIKE {arg(f'%{d}%')} OR b.device_ip LIKE {arg(f'{d}%')})")
  if q and q.strip():
    p = arg(f"%{_escape_like(q.strip())}%")
    parts.append(f"(b.boardname ILIKE {p} OR b.boardtype ILIKE {p} OR b.boardrole ILIKE {p})")
  for col in FACETS:
    v = filters.get(col)
    if v == "(none)":
      parts.append(f"b.{col} IS NULL")
    elif v:
      parts.append(f"b.{col} = {arg(v)}")
  return ("WHERE " + " AND ".join(parts)) if parts else "", args


async def list_boards(
  device: str | None = None, q: str | None = None, filters: dict[str, str | None] | None = None,
  sort: str = "device_name", order: str = "asc", page: int = 1, size: int = 50,
) -> dict[str, Any]:
  where, args = _where(device, q, filters or {})
  direction = "DESC" if order.lower() == "desc" else "ASC"
  col = SORTS.get(sort, SORTS["device_name"])
  n = len(args)
  rows, total = await asyncio.gather(
    db.fetch(f"""SELECT {COLS} FROM board b {where}
      ORDER BY {col} {direction} NULLS LAST, b.device_name, b.boardname, b.id LIMIT ${n + 1} OFFSET ${n + 2}""",
      *args, size, (page - 1) * size),
    db.fetchval(f"SELECT count(*) FROM board b {where}", *args),
  )
  return {"items": [rec(r) for r in rows], "total": total, "page": page, "size": size}


@ttl_cache(600)
async def facets() -> dict[str, list[dict[str, Any]]]:
  """Dropdown values with fleet-wide counts (NULL shown as "(none)")."""
  rows = await db.fetch(" UNION ALL ".join(
    f"SELECT '{c}' AS dim, coalesce({c}, '(none)') AS v, count(*) AS c FROM board GROUP BY 2" for c in FACETS))
  out: dict[str, list[dict[str, Any]]] = {c: [] for c in FACETS}
  for r in sorted(rows, key=lambda r: -r["c"]):
    out[r["dim"]].append({"value": r["v"], "count": r["c"]})
  return out
