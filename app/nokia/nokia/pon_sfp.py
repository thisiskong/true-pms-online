"""Item 8: PON-SFP — PON SFP inventory from the fiber:fiber config.

Note: pon-sfp:show-sfp-inventory action does not exist on firmware 25.6.
Equivalent data (xpon-type, model-name, vendorpn) is available from the
`fiber:fiber` config already fetched by AC-FIBER, which is passed in here
(`fiber_cfg`) so no second GET per fiber is needed.
vendorpn is parsed from model-name field: '... (3FE47581BD)' -> '3FE47581BD'
"""

import logging
import re
from pathlib import Path
from .client import AltiplanoClient, save

log = logging.getLogger(__name__)


XPON_TO_MODULECLASS = {
  "gpon":        "GPON CLASS B+",
  "xgs-pon":     "XGS-PON",
  "mpm-gpon-xgs": "GPON/XGS-PON (combo)",
}


def _parse_vendorpn(model_name: str) -> str | None:
  """Extract part number from model-name: 'XGS/GPON SFP-DD ... (3FE47581BD)' -> '3FE47581BD'"""
  m = re.search(r"\(([^)]+)\)\s*$", model_name or "")
  return m.group(1) if m else None


def normalize(cfg: dict, fiber_name: str) -> dict:
  d = cfg or {}
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


def run(client: AltiplanoClient, output_dir: Path, fibers_by_olt: dict[str, list[dict]],
        fiber_cfg: dict[str, dict]) -> dict[str, dict]:
  all_normalized: dict[str, dict] = {}

  for olt, fibers in fibers_by_olt.items():
    log.info("[PON-SFP] OLT=%s (%d fibers) ...", olt, len(fibers))
    for fiber in fibers:
      fname = fiber["fiber_name"]
      all_normalized[fname] = normalize(fiber_cfg.get(fname, {}), fname)
    sample = list(all_normalized.values())[-1] if all_normalized else {}
    log.info("  moduleclass=%s vendorpn=%s", sample.get("moduleclass"), sample.get("vendorpn"))

  save(output_dir, "08_pon_sfp", fiber_cfg, {"pon_sfp": all_normalized, "count": len(all_normalized)})
  return all_normalized
