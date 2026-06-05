"""Item 8: PON-SFP — PON SFP inventory via AC fiber:fiber GET.

Note: pon-sfp:show-sfp-inventory action does not exist on firmware 25.6.
Equivalent data (xpon-type, model-name, vendorpn) is available via fiber:fiber GET.
vendorpn is parsed from model-name field: '... (3FE47581BD)' -> '3FE47581BD'
"""

import re
from pathlib import Path
from .client import AltiplanoClient, save


XPON_TO_MODULECLASS = {
  "gpon":        "GPON CLASS B+",
  "xgs-pon":     "XGS-PON",
  "mpm-gpon-xgs": "GPON/XGS-PON (combo)",
}


def _ac_path(rel: str, fiber_name: str) -> str:
  return f"/{rel}-ac/rest/restconf/data/ibn:ibn/intent={fiber_name},fiber/intent-specific-data/fiber:fiber"


def _parse_vendorpn(model_name: str) -> str | None:
  """Extract part number from model-name: 'XGS/GPON SFP-DD ... (3FE47581BD)' -> '3FE47581BD'"""
  m = re.search(r"\(([^)]+)\)\s*$", model_name or "")
  return m.group(1) if m else None


def fetch(client: AltiplanoClient, fiber_name: str) -> dict:
  return client.get(_ac_path(client.rel, fiber_name))


def normalize(raw: dict, fiber_name: str) -> dict:
  d = raw.get("fiber:fiber", {})
  xpon_type = d.get("xpon-type", "")
  pon_ports = d.get("pon-port", [])
  port = pon_ports[0] if pon_ports else {}
  model_name = port.get("model-name", "")
  return {
    "fiber_name": fiber_name,
    "xpon_type": xpon_type,
    "moduleclass": XPON_TO_MODULECLASS.get(xpon_type),
    "vendorpn": _parse_vendorpn(model_name),
    "model_name": model_name,
    "admin_state": port.get("admin-state"),
    "pon_id": port.get("pon-id"),
    "port_profile": port.get("port-profile"),
    "cage_mode": port.get("cage-mode"),
    "line_rate": port.get("line-rate"),
  }


def run(client: AltiplanoClient, output_dir: Path, fibers_by_olt: dict[str, list[dict]]) -> dict[str, dict]:
  all_raw: dict[str, dict] = {}
  all_normalized: dict[str, dict] = {}

  for olt, fibers in fibers_by_olt.items():
    print(f"[PON-SFP] OLT={olt} ({len(fibers)} fibers) ...")
    for fiber in fibers:
      fname = fiber["fiber_name"]
      raw = fetch(client, fname)
      norm = normalize(raw, fname)
      all_raw[fname] = raw
      all_normalized[fname] = norm
    sample = list(all_normalized.values())[-1] if all_normalized else {}
    print(f"  moduleclass={sample.get('moduleclass')} vendorpn={sample.get('vendorpn')}")

  save(output_dir, "08_pon_sfp", all_raw, {"pon_sfp": all_normalized, "count": len(all_normalized)})
  return all_normalized
