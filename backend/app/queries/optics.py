"""PON port optic class (B+, C+, C++, D) normalised from ponport.moduleclass, with vendorpn as a fallback.

Each OLT vendor writes the class its own way ("gpon-classbplus", "GPON/B+", "classbplus",
"GPON CLASS B+ SFP OLT", "GPON&XGS-PON_COMBO/MPM_C+/EC++C+", ...). When moduleclass carries no class
(empty, "N/A", "invalid-invalid", ...), the part number is looked up in a table learned from the
ports that do report a class: the majority class for that vendorpn.

The part number text itself is NOT parsed: "LTE3680M-BC+" is reported as B+ on thousands of ports.
"""
import asyncio
import logging
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from app import db

log = logging.getLogger(__name__)

GPON = "GPON"
COMBO = "GPON+XGS-PON"
ABSENT = "absent"

# vendorpn -> (class, tech) that beats the learned table, for part numbers known to be misreported.
OVERRIDES: dict[str, tuple[str, str]] = {}

REFRESH_S = 6 * 3600


@dataclass(frozen=True)
class Optic:
  cls: str | None      # "B+", "C+", "C++", "D", "absent" (no optic in the port), or None (unknown)
  tech: str | None     # GPON, GPON+XGS-PON, or None
  source: str | None   # "moduleclass", "vendorpn", or None


UNKNOWN = Optic(None, None, None)


def _class_of(token: str) -> str | None:
  """Class at the end of a token: "ec++c+" -> C+, "mpm_d" -> D, "classcplusplus" -> C++."""
  t = token.replace("plus", "+").strip(" ()")
  for suffix, cls in (("c++", "C++"), ("c+", "C+"), ("b+", "B+"), ("+i", "B+")):
    if t.endswith(suffix):
      return cls
  return "D" if re.search(r"(^|[^a-z])d$", t) or t.endswith("classd") else None


def parse_moduleclass(mc: str | None) -> Optic:
  """Class and technology from the moduleclass text alone."""
  if not mc or not mc.strip():
    return UNKNOWN
  s = mc.strip().lower()
  if s == "absent":
    return Optic(ABSENT, None, "moduleclass")
  if "xgs" in s:
    # Combo optics: the GPON class is the MPM_ part, else what follows the last "/".
    m = re.search(r"mpm_([a-z+]+)", s)
    token = m.group(1) if m else s.rsplit("/", 1)[1] if "/" in s else ""
    cls = _class_of(token.split("-")[-1]) if token else None
    return Optic(cls, COMBO, "moduleclass" if cls else None)
  if "gpon" not in s and "class" not in s and "plus" not in s:
    return UNKNOWN            # "N/A", "0", "10Gbase-SR", "invalid-invalid", ...
  cls = None
  if "cplusplus" in s or "c++" in s:
    cls = "C++"
  elif "cplus" in s or "c+" in s:
    cls = "C+"
  elif "bplus" in s or "b+" in s:
    cls = "B+"
  elif re.search(r"(class |/)d\b", s):
    cls = "D"
  return Optic(cls, GPON, "moduleclass") if cls else Optic(None, GPON if "gpon" in s else None, None)


def _pn_key(pn: str | None) -> str:
  return (pn or "").strip().upper()


# ---- vendorpn table learned from the database --------------------------------------------------

_pn_table: dict[str, tuple[str, str]] = {}
_pn_loaded_at = 0.0
_pn_lock = asyncio.Lock()


def build_pn_table(rows: list[tuple[str | None, str | None, int]]) -> dict[str, tuple[str, str]]:
  """(moduleclass, vendorpn, ports) rows -> vendorpn -> majority (class, tech)."""
  votes: dict[str, Counter] = defaultdict(Counter)
  for mc, pn, n in rows:
    o = parse_moduleclass(mc)
    if o.cls and o.cls != ABSENT and _pn_key(pn) and o.tech:
      votes[_pn_key(pn)][(o.cls, o.tech)] += n
  return {pn: c.most_common(1)[0][0] for pn, c in votes.items()}


async def pn_table() -> dict[str, tuple[str, str]]:
  """The learned table, rebuilt every few hours; on a DB error the previous table is kept."""
  global _pn_table, _pn_loaded_at
  if time.monotonic() - _pn_loaded_at < REFRESH_S and _pn_loaded_at:
    return _pn_table
  async with _pn_lock:
    if time.monotonic() - _pn_loaded_at < REFRESH_S and _pn_loaded_at:
      return _pn_table
    try:
      rows = await db.fetch(
        "SELECT moduleclass, vendorpn, count(*) AS n FROM ponport WHERE vendorpn IS NOT NULL GROUP BY 1, 2")
      _pn_table = build_pn_table([(r["moduleclass"], r["vendorpn"], r["n"]) for r in rows])
    except Exception:  # pragma: no cover - keep serving with what we have
      log.exception("could not build the vendorpn -> optic class table")
    _pn_loaded_at = time.monotonic()
  return _pn_table


def classify(mc: str | None, pn: str | None, table: dict[str, tuple[str, str]]) -> Optic:
  """moduleclass first; vendorpn (overrides, then the learned table) when it gives no class."""
  o = parse_moduleclass(mc)
  if o.cls:
    return o
  hit = OVERRIDES.get(_pn_key(pn)) or table.get(_pn_key(pn))
  if hit and (o.tech is None or o.tech == hit[1]):
    return Optic(hit[0], hit[1], "vendorpn")
  return o


def optic_fields(d: dict[str, Any], table: dict[str, tuple[str, str]]) -> dict[str, Any]:
  o = classify(d.get("moduleclass"), d.get("vendorpn"), table)
  return {"optic_class": o.cls, "optic_tech": o.tech, "optic_class_source": o.source}
