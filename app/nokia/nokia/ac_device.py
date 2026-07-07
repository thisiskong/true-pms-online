"""AC-DEVICE — list OLTs and pull per-device config/state/boards via AC.

Replaces the former ES-DEVICE (item 3) + SLOT-INV (item 6). Devices are
enumerated from the shared `ac.list_intents` call (intent-types `device-mf`
and `device-df`), then each device's bare intent GET yields config
(`{type}:{type}`), operational state (`{type}:{type}-state`), and boards in a
single request.
"""

import json
import logging
from pathlib import Path
from typing import Optional
from .client import AltiplanoClient, save
from . import ac

log = logging.getLogger(__name__)

DEVICE_INTENT_TYPES = ("device-mf", "device-df")


def _intent_type_of(target: str, intents: list[dict]) -> Optional[str]:
  for i in intents:
    if i.get("target") == target and i.get("intent-type") in DEVICE_INTENT_TYPES:
      return i["intent-type"]
  return None


def normalize(intent: dict, itype: str) -> dict:
  name = intent.get("target")
  isd = intent.get("intent-specific-data", {})
  cfg = isd.get(f"{itype}:{itype}", {})
  state = isd.get(f"{itype}:{itype}-state", {})
  boards = cfg.get("boards", [])
  hw_type = cfg.get("hardware-type")
  swversion = state.get("actual-active-software-on-device")
  return {
    # --- device row (consumed by assemble) ---
    "name":                   name,
    "ip":                     cfg.get("ip-address"),
    "descr":                  hw_type,
    "swversion":              swversion,
    "vendor":                 "Nokia",
    "required-network-state": intent.get("required-network-state"),
    "reachable":              state.get("reachable"),
    # --- slot/board detail (consumed by assemble boards + mapper) ---
    "hardware_type":          hw_type,
    "transport_protocol":     cfg.get("transport-protocol"),
    "device_manager":         cfg.get("device-manager"),
    "device_version":         cfg.get("device-version"),
    "ip_port":                cfg.get("ip-port"),
    "boards":                 boards,
    "lt_slot_names":          [b.get("slot-name") for b in boards
                               if (b.get("slot-name") or "").upper().startswith("LT")],
  }


def run(client: AltiplanoClient, output_dir: Path,
        intents: list[dict]) -> tuple[list[dict], dict[str, dict]]:
  """Return (devices, slots).

  devices — list of device rows for assemble.
  slots   — per-device detail keyed by name (boards for mapper, config fields).
  """
  targets = ac.targets_of_type(intents, *DEVICE_INTENT_TYPES)
  log.info("[AC-DEVICE] %d devices (%s)", len(targets), "/".join(DEVICE_INTENT_TYPES))

  all_raw: dict[str, dict] = {}
  devices: list[dict] = []
  slots: dict[str, dict] = {}

  for name in targets:
    itype = _intent_type_of(name, intents)
    log.info("[AC-DEVICE] OLT=%s type=%s ...", name, itype)
    intent = ac.get_intent(client, name, itype)
    norm = normalize(intent, itype)
    all_raw[name] = intent
    devices.append(norm)
    slots[name] = norm
    log.info("  ip=%s sw=%s reachable=%s boards=%s",
             norm["ip"], norm["swversion"], norm["reachable"],
             [b.get("slot-name") for b in norm["boards"]])

  save(output_dir, "03_ac_device", all_raw,
       {"devices": devices, "count": len(devices)})
  return devices, slots


def run_normalize(output_dir: Path,
                   intents: list[dict]) -> tuple[list[dict], dict[str, dict]]:
  """Rebuild (devices, slots) from 03_ac_device_raw.json — no network."""
  all_raw: dict[str, dict] = json.loads((output_dir / "03_ac_device_raw.json").read_text())
  targets = ac.targets_of_type(intents, *DEVICE_INTENT_TYPES)

  devices: list[dict] = []
  slots: dict[str, dict] = {}

  for name in targets:
    itype = _intent_type_of(name, intents)
    intent = all_raw.get(name)
    if intent is None:
      log.warning("[AC-DEVICE] no raw data for %s, skipping", name)
      continue
    norm = normalize(intent, itype)
    devices.append(norm)
    slots[name] = norm

  save(output_dir, "03_ac_device", all_raw,
       {"devices": devices, "count": len(devices)})
  return devices, slots
