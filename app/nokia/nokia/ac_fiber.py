"""AC-FIBER — list fibers (PON ports) per OLT and pull config via AC.

Replaces the former ES-FIBER (item 4). Fibers are enumerated from the shared
`ac.list_intents` call (intent-type `fiber`) and grouped to their OLT by target
prefix (`{olt}-{slot}-{pon}`). Each fiber's bare intent GET yields the
`fiber:fiber` config (xpon-type, pon-port, ...) which is also returned raw so
PON-SFP can reuse it without a second fetch.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional
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

def _parse_ponport(pon_id: str) -> Optional[str]:
  """Derive ponport from pon-id ('PON_14' -> '1-1-1-14') or ('LT2.PON14' -> '1-1-2-14')."""
  m = re.match(r"PON_(\d+)$", pon_id or "", re.IGNORECASE)
  if m:
    return f"1-1-1-{int(m.group(1))}"
  m = re.match(r"LT(\d+)\.PON(\d+)$", pon_id or "", re.IGNORECASE)
  if m:
    return f"1-1-{int(m.group(1))}-{int(m.group(2))}"
  return None

def normalize(intent: dict) -> dict:
  fiber_name = intent.get("target")
  cfg = intent.get("intent-specific-data", {}).get("fiber:fiber", {})
  xpon_raw = cfg.get("xpon-type", "")
  port = (cfg.get("pon-port") or [{}])[0]
  device_name = port.get("device-name")
  pon_id = port.get("pon-id", "")
  ponport = _parse_ponport(pon_id)
  log.info(f"ac_fiber: ponport={device_name}|{pon_id}|{ponport}")
  return {
    "olt_name": port.get("device-name"),
    "fiber_name": fiber_name,
    "ponport": ponport,
    "xpon_type_raw": xpon_raw,
    "iftype": XPON_TYPE_MAP.get(xpon_raw),
    "ifspeed": IFSPEED_MAP.get(xpon_raw),
    "pon_id": pon_id,
    "port_profile": port.get("port-profile"),
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


def run_normalize(output_dir: Path, devices: list[dict],
                   intents: list[dict]) -> tuple[dict[str, list[dict]], dict[str, dict]]:
  """Rebuild (fibers_by_olt, fiber_cfg_by_name) from 04_ac_fiber_raw.json — no network."""
  all_raw: dict[str, dict] = json.loads((output_dir / "04_ac_fiber_raw.json").read_text())
  fiber_targets = ac.targets_of_type(intents, FIBER_INTENT_TYPE)

  fibers_by_olt: dict[str, list[dict]] = {}
  fiber_cfg: dict[str, dict] = {}

  for dev in devices:
    olt = dev["name"]
    names = [t for t in fiber_targets if t.startswith(f"{olt}-")]
    fibers = []
    for fname in names:
      intent = all_raw.get(fname)
      if intent is None:
        log.warning("[AC-FIBER] no raw data for %s, skipping", fname)
        continue
      fiber_cfg[fname] = intent.get("intent-specific-data", {}).get("fiber:fiber", {})
      fibers.append(normalize(intent))
    fibers_by_olt[olt] = fibers

  total = sum(len(v) for v in fibers_by_olt.values())
  save(output_dir, "04_ac_fiber", all_raw, {"fibers_by_olt": fibers_by_olt, "total": total})
  return fibers_by_olt, fiber_cfg
