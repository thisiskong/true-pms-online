"""Access-id (circuit number) lookup.

odn_onu.accessid (indexed, unique per ONU) -> OLT name + PON port + ONT id + ODN path. The OLT name maps to
device.id (indexed name), which links the subscriber to the device dashboard and the fiber score.
Trouble tickets come from `ticket` (no accessid index; ~1M rows, historical extract).
"""
import asyncio
import re
from typing import Any

from app import db
from app.cache import ttl_cache
from app.queries import fiber
from app.queries.models import rec

ACCESSID_RE = re.compile(r"^[0-9A-Za-z._-]{4,50}$")
MAX_TICKETS = 20


def normalize(raw: str) -> str:
  """Trim and drop inner spaces, so a pasted '9605 163 336' still matches."""
  v = re.sub(r"\s+", "", raw or "")
  if not ACCESSID_RE.match(v):
    raise ValueError(f"'{raw}' is not a valid access id (expected 4-50 letters/digits, e.g. 9605163336)")
  return v


async def find_onu(accessid: str) -> dict[str, Any] | None:
  r = await db.fetchrow(
    """SELECT o.accessid, o.device AS device_name, o.ponport, o.ontid, o.devicesn,
      o.l1name, o.l2name, o.l1ratio, o.l2ratio, o.splitratio, o.l1len, o.l2len, o.dropwire, o.ranging,
      o.moduleclass, o.l2date, o.hsidate,
      d.id AS device_id, d.ip AS device_ip, d.vendor AS device_vendor, d.model AS device_model,
      d.region, d.province, d.sitename
    FROM odn_onu o
    LEFT JOIN LATERAL (
      SELECT id, ip, vendor, model, region, province, sitename FROM device
      WHERE name = o.device ORDER BY lastseen DESC NULLS LAST, id LIMIT 1
    ) d ON true
    WHERE o.accessid = $1""",
    accessid,
  )
  return rec(r) if r else None


async def list_tickets(accessid: str, limit: int = 10) -> dict[str, Any]:
  rows = await db.fetch(
    """SELECT ticketid, createtime, completetime, faulttype, faultcause, subcategory, faultstatus, networkdisp
    FROM ticket WHERE accessid = $1 ORDER BY createtime DESC NULLS LAST, ticketid DESC LIMIT $2""",
    accessid, limit + 1,
  )
  return {"items": [rec(r) for r in rows[:limit]], "truncated": len(rows) > limit}


@ttl_cache(3600)
async def ticket_range() -> dict[str, Any]:
  """Date range of the ticket extract (it is a historical load, not live)."""
  r = await db.fetchrow("SELECT min(tstamp) AS data_from, max(tstamp) AS data_to FROM ticket")
  return rec(r) if r else {"data_from": None, "data_to": None}


async def _fiber_score(onu: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
  """(score, None) or (None, reason it has no score)."""
  try:
    s = await fiber.onu_brief(onu["device_name"], onu["ponport"], onu["ontid"])
    if s is None:
      return None, await fiber.unscored_reason(None, onu["device_name"], onu["ponport"], onu["ontid"])
    return s, None
  except fiber.RunNotFound as e:
    return None, str(e)


async def lookup(raw: str, tickets: int = 10) -> dict[str, Any] | None:
  """Everything known about one access id, or None when no ONU has it."""
  accessid = normalize(raw)
  onu = await find_onu(accessid)
  if onu is None:
    return None
  (score, fiber_note), tix, rng = await asyncio.gather(_fiber_score(onu), list_tickets(accessid, tickets), ticket_range())
  device = {
    "id": onu.pop("device_id"), "name": onu["device_name"], "ip": onu.pop("device_ip"),
    "vendor": onu.pop("device_vendor"), "model": onu.pop("device_model"),
    "region": onu.pop("region"), "province": onu.pop("province"), "sitename": onu.pop("sitename"),
  }
  return {
    "accessid": accessid, "onu": onu, "device": device, "fiber": score, "fiber_note": fiber_note,
    "tickets": {**tix, **rng},
  }
