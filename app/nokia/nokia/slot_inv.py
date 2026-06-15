"""Item 6: SLOT-INV — OLT configuration and board inventory via AC device-mf GET.

Note: The eqpt:slot-inventory IBN action is not present on firmware 25.6.
Equivalent data is available at the device-mf:device-mf intent-specific-data path.
"""

import logging
from pathlib import Path
from .client import AltiplanoClient, save

log = logging.getLogger(__name__)

HARDWARE_TYPE_TO_OLTTYPE = {
  "LS-MF-LANT-A": "MF-2",
  "LS-MF-LMNT-A": "MF-2",
  "LS-DF-CFXR-H": "DF-16GM",
}


def _ac_path(rel: str, olt_name: str) -> str:
  return f"/{rel}-ac/rest/restconf/data/ibn:ibn/intent={olt_name},device-mf/intent-specific-data/device-mf:device-mf"


def fetch(client: AltiplanoClient, olt_name: str) -> dict:
  return client.get(_ac_path(client.rel, olt_name))


def normalize(raw: dict, olt_name: str) -> dict:
  d = raw.get("device-mf:device-mf", {})
  hw_type = d.get("hardware-type", "")
  boards = d.get("boards", [])
  return {
    "olt_name":                        olt_name,
    "vendor":                          "Nokia",
    "olttype":                         HARDWARE_TYPE_TO_OLTTYPE.get(hw_type),
    "device-manager":                  d.get("device-manager"),
    "device-template":                 d.get("device-template"),
    "device-version":                  d.get("device-version"),
    "hardware-type":                   hw_type,
    "ihub-device-template":            d.get("ihub-device-template"),
    "ihub-version":                    d.get("ihub-version"),
    "ip-address":                      d.get("ip-address"),
    "ip-port":                         d.get("ip-port"),
    "partition-access-profile":        d.get("partition-access-profile"),
    "push-nav-configuration-to-device": d.get("push-nav-configuration-to-device"),
    "timezone-name":                   d.get("timezone-name"),
    "transport-protocol":              d.get("transport-protocol"),
    "username":                        d.get("username"),
    "boards":                          boards,
  }


def run(client: AltiplanoClient, output_dir: Path, devices: list[dict]) -> dict[str, dict]:
  all_raw: dict[str, dict] = {}
  all_normalized: dict[str, dict] = {}

  for dev in devices:
    olt = dev["name"]
    log.info("[SLOT-INV] OLT=%s ...", olt)
    raw = fetch(client, olt)
    norm = normalize(raw, olt)
    all_raw[olt] = raw
    all_normalized[olt] = norm
    log.info("  sw=%s olttype=%s boards=%s", norm["device-version"], norm["olttype"], [b.get("slot-name") for b in norm["boards"]])

  save(output_dir, "06_slot_inv", all_raw, all_normalized)
  return all_normalized
