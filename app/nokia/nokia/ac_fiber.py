"""AC-FIBER — list fibers (PON ports) per OLT and pull config via AC.

Replaces the former ES-FIBER (item 4). Fibers are enumerated from the shared
`ac.list_intents` call (intent-type `fiber`) and grouped to their OLT by target
prefix (`{olt}-{slot}-{pon}`). Each fiber's bare intent GET yields the
`fiber:fiber` config (xpon-type, pon-port, ...) which is also returned raw so
PON-SFP can reuse it without a second fetch.
"""

import logging
import re
from pathlib import Path
from .client import AltiplanoClient, save
from . import ac

log = logging.getLogger(__name__)

FIBER_INTENT_TYPE = "fiber"

XPON_TYPE_MAP = {
  "gpon": "gpon",
  "xgs-pon": "xgs-pon",
  "mpm-gpon-xgs": "xgs-pon",
}

IFSPEED_MAP = {
  "gpon": 2488000000,
  "xgs-pon": 10000000000,
  "mpm-gpon-xgs": 10000000000,
}

DL_BW_MAP = {"gpon": 2488, "xgs-pon": 10240, "mpm-gpon-xgs": 10240}
UL_BW_MAP = {"gpon": 1244, "xgs-pon": 10240, "mpm-gpon-xgs": 10240}


def _parse_ponport(fiber_name: str, pon_id: str) -> str | None:
  """Derive ponport from pon-id ('LT1.PON16' -> '1-1-1-16') or fiber name."""
  m = re.match(r"LT(\d+)\.PON(\d+)$", pon_id or "", re.IGNORECASE)
  if m:
    return f"1-1-{int(m.group(1))}-{int(m.group(2))}"
  m = re.match(r".*\.L(\d+)P(\d+)$", fiber_name or "", re.IGNORECASE)
  if m:
    return f"1-1-{int(m.group(1))}-{int(m.group(2))}"
  return None


def normalize(intent: dict) -> dict:
  fiber_name = intent.get("target")
  cfg = intent.get("intent-specific-data", {}).get("fiber:fiber", {})
  xpon_raw = cfg.get("xpon-type", "")
  port = (cfg.get("pon-port") or [{}])[0]
  pon_id = port.get("pon-id", "")
  return {
    "olt_name": port.get("device-name"),
    "fiber_name": fiber_name,
    "ponport": _parse_ponport(fiber_name, pon_id),
    "xpon_type_raw": xpon_raw,
    "iftype": XPON_TYPE_MAP.get(xpon_raw),
    "ifspeed": IFSPEED_MAP.get(xpon_raw),
    "l1_dl_max_bw": DL_BW_MAP.get(xpon_raw),
    "l1_ul_max_bw": UL_BW_MAP.get(xpon_raw),
    "pon_id": pon_id,
    "l1sp": port.get("port-profile"),
    "required_network_state": intent.get("required-network-state"),
  }


def run(client: AltiplanoClient, output_dir: Path, devices: list[dict],
        intents: list[dict]) -> tuple[dict[str, list[dict]], dict[str, dict]]:
  """Return (fibers_by_olt, fiber_cfg_by_name).

  fiber_cfg_by_name maps fiber_name -> `fiber:fiber` config dict, reused by PON-SFP.
  """
  fiber_targets = ac.targets_of_type(intents, FIBER_INTENT_TYPE)

  all_raw: dict[str, dict] = {}
  fibers_by_olt: dict[str, list[dict]] = {}
  fiber_cfg: dict[str, dict] = {}

  for dev in devices:
    olt = dev["name"]
    names = [t for t in fiber_targets if t.startswith(f"{olt}-")]
    log.info("[AC-FIBER] OLT=%s fibers=%d ...", olt, len(names))
    fibers = []
    for fname in names:
      intent = ac.get_intent(client, fname, FIBER_INTENT_TYPE)
      all_raw[fname] = intent
      fiber_cfg[fname] = intent.get("intent-specific-data", {}).get("fiber:fiber", {})
      fibers.append(normalize(intent))
    fibers_by_olt[olt] = fibers

  total = sum(len(v) for v in fibers_by_olt.values())
  save(output_dir, "04_ac_fiber", all_raw, {"fibers_by_olt": fibers_by_olt, "total": total})
  log.info("[AC-FIBER] total fibers: %d", total)
  return fibers_by_olt, fiber_cfg
