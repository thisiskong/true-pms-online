"""Assemble device, intf, and ponport rows from collected API data and save as JSONL.

Field value conventions:
  "NotSupported"  — field has no equivalent in Nokia Altiplano NBI (requires LLDP, SNMP, or manual mapping)
  "NotImplement"  — field is available from Nokia API but not yet collected (blocked or pending implementation)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

def _now() -> str:
  return datetime.now(timezone.utc).isoformat()


def _save_jsonl(path: Path, rows: list[dict]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("w", encoding="utf-8") as f:
    for row in rows:
      f.write(json.dumps(row, ensure_ascii=False) + "\n")
  log.info("  saved: %s (%d rows)", path.name, len(rows))


# ---------------------------------------------------------------------------
# device  (45 fields — from Nokia-Device-Discovery.md §device table)
# ---------------------------------------------------------------------------

def build_device(devices: list[dict], slots: dict[str, dict]) -> list[dict]:
  rows = []
  ts = _now()
  for dev in devices:
    name = dev["name"]
    slot = slots.get(name, {})
    rows.append({
      # --- available from ES-DEVICE + SLOT-INV ---
      "name":             name,
      "ip":               dev.get("ip"),
      "vendor":           "Nokia",
      "descr":            slot.get("hardware_type") or dev.get("descr"),
      "swversion":        slot.get("swversion") or dev.get("swversion"),
      "transport_protocol": slot.get("transport_protocol"),
      "lt_slots":         slot.get("lt_slot_names", []),
      "agent":            "nokia-altiplano",
      "required-network-state": dev.get("required-network-state"),
      "last_modify_by":   "nokia-altiplano",
      "last_modify_at":   ts,
      "lastseen":         ts,
      "first":            ts,
      "model":            slot.get("hardware_type") or dev.get("descr"),
      "chassisid":        None,
      # --- NotSupported: not available from Nokia NBI ---
      # "network":          None,
      # "region":           None,
      # "province":         None,
      # "sitename":         None,
      # "latitude":         None,   # static site coordinates
      # "longitude":        None,   # static site coordinates
      # "community":        None,   # SNMP community string — external credential
      # "dn":               None,
      # "pn":               None,
      # "hop":              None,
      # "rn":               None,
      # "ringid":           None,
      # "ringtopo":         None,
      # "topology":         None,
      # "uplink_ip1":       None,
      # "uplink_ip2":       None,
      # "uplink_model1":    None,
      # "uplink_model2":    None,
      # "uplink_site1":     None,
      # "uplink_site2":     None,
      # "a_homing_id":      None,
      # "a_homing_site":    None,
      # "b_homing_id":      None,
      # "b_homing_site":    None,
      # "c_homing_id":      None,
      # "c_homing_site":    None,
    })
  return rows


# ---------------------------------------------------------------------------
# intf  (32 fields — from Nokia-Device-Discovery.md §intf table)
# ---------------------------------------------------------------------------

# Maps port-id type token to module class string
_PORT_TYPE_TO_MODULECLASS = {
  "xfp":  "10GE-XFP",
  "qsfp": "100GE-QSFP28",
  "sfp":  "1GE-SFP",
}

# Maps wavelength (nm string) to media type
_WAVELENGTH_TO_MEDIATYPE = {
  "850":  "MM",
  "1310": "SM",
  "1490": "SM",
  "1550": "SM",
}


def _port_moduleclass(port_id: str) -> Optional[str]:
  """Derive moduleclass from port_id token e.g. 'nt-a:xfp:1' -> '10GE-XFP'."""
  for token, cls in _PORT_TYPE_TO_MODULECLASS.items():
    if f":{token}:" in port_id or port_id.endswith(f":{token}"):
      return cls
  return None


def _vendorpn(part_number: str) -> Optional[str]:
  """Return first whitespace token of part_number as the vendor PN."""
  pn = (part_number or "").strip()
  return pn.split()[0] if pn and pn != "-" else None


def build_intf(devices: list[dict], uplink_sfp: dict[str, list[dict]]) -> list[dict]:
  ts = _now()
  device_map = {d["name"]: d for d in devices}
  rows = []

  for olt, sfp_list in uplink_sfp.items():
    dev = device_map.get(olt, {})
    for sfp in sfp_list:
      port_id = sfp.get("port_id", "")
      port_no = sfp.get("port_no", "")
      port_descr = sfp.get("port_description", "")
      part_no = _vendorpn(sfp.get("part_number", ""))
      wave = (sfp.get("wave_length") or "").strip().lstrip("0") or None
      oper = sfp.get("oper_state")
      admin = sfp.get("admin_state")
      rows.append({
        # --- available from ES-DEVICE ---
        "device_ip":        dev.get("ip"),
        "device_name":      olt,
        "iftype":           "ethernetCsmacd",
        "last_modify_by":   "nokia-altiplano",
        "last_modify_at":   ts,
        "lastseen":         ts,
        "first":            ts,
        # --- available from UPLINK-SFP (item 7) ---
        "ifname":           port_id,
        "ifdescr":          port_descr,
        "name":             port_id,
        "ifadmin":          "down" if admin == "disable" else "up" if admin else None,
        "ifoper":           oper if oper and oper != "-" else None,
        "moduleclass":      _port_moduleclass(port_id),
        "vendorpn":         part_no,
        "mediatype":        _WAVELENGTH_TO_MEDIATYPE.get(wave) if wave else None,
        "id":               None,
        "device_id":        None,
        "ifspeed":          sfp.get("speed_bps"),
        "ifindex":          port_no,
        "ifphyaddr":        None,
        "ifalias":          None,
        "ifconn":           None,
      })
  return rows


# ---------------------------------------------------------------------------
# ponport  (29 fields — from Nokia-Device-Discovery.md §ponport table)
# ---------------------------------------------------------------------------

def build_ponport(
  fibers_by_olt: dict[str, list[dict]],
  pon_sfp: dict[str, dict],
  ont_counts: dict[str, int],
  devices: list[dict],
) -> list[dict]:
  device_map = {d["name"]: d for d in devices}
  rows = []
  ts = _now()
  for olt, fibers in fibers_by_olt.items():
    dev = device_map.get(olt, {})
    for fiber in fibers:
      fname = fiber["fiber_name"]
      sfp = pon_sfp.get(fname, {})
      rows.append({
        # --- available from ES-FIBER ---
        "device_name":      olt,
        "device_ip":        dev.get("ip"),
        "ifname":           fiber.get("pon_id"), # fname,
        "ifdescr":          fiber.get("pon_id"), # fname,
        "ponport":          fiber.get("ponport"),
        "iftype":           fiber.get("iftype"),
        "ifspeed":          fiber.get("ifspeed"),
        "xpon_type":        fiber.get("xpon_type_raw"),
        "pon_id":           fiber.get("pon_id"),
        "name":             f"{fiber.get('ponport')}",
        # --- available from PON-SFP (item 8) ---
        "moduleclass":      sfp.get("moduleclass"),
        "vendorpn":         sfp.get("vendorpn"),
        "model_name":       sfp.get("model_name"),
        # --- available from ES-ONT (item 5) ---
        "ifconn":           None,
        # --- available (defaults) ---
        "last_modify_by":   "nokia-altiplano",
        "last_modify_at":   ts,
        "lastseen":         ts,
        "first":            ts,
        # --- available from PON-SFP (fiber:fiber AC) and ES-FIBER ---
        "ifadmin":          "down" if sfp.get("admin_state") == "locked" else "up",
        "ifoper":           "up" if fiber.get("required_network_state") == "active" else "down" if fiber.get("required_network_state") else None,
        "id":               None,
        "device_id":        None,
        "ifindex":          fiber.get("pon_id"),
        "ifphyaddr":        None,
        "ifalias":          None,
      })
  return rows


# ---------------------------------------------------------------------------
# ont  (per-ONT operational info from show-ont-info)
# ---------------------------------------------------------------------------

def build_ont(
  fibers_by_olt: dict[str, list[dict]],
  ont_names_by_fiber: dict[str, list[str]],
  ont_info: dict[str, dict],
  devices: list[dict],
) -> list[dict]:
  device_map = {d["name"]: d for d in devices}
  rows = []
  ts = _now()
  for olt, fibers in fibers_by_olt.items():
    dev = device_map.get(olt, {})
    for fiber in fibers:
      fname = fiber["fiber_name"]
      for ont_name in ont_names_by_fiber.get(fname, []):
        info = ont_info.get(ont_name, {})
        rows.append({
          "device_name":   olt,
          "device_ip":     dev.get("ip"),
          "fiber_name":    fname,
          "ponport":       fiber.get("ponport"),
          "ont_name":      ont_name,
          "oper_state":    info.get("oper_state"),
          "admin_state":   info.get("admin_state"),
          "rxpwr":         info.get("rx_signal"),
          "txpwr":         info.get("tx_signal"),
          "distance":      info.get("distance"),
          "serial_number": info.get("serial_number"),
          "hw_type":       info.get("hw_type"),
          "sw_version":    info.get("sw_version"),
          "last_modify_by": "nokia-altiplano",
          "last_modify_at": ts,
          "lastseen":       ts,
          "first":          ts,
        })
  return rows


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def run(
  output_dir: Path,
  devices: list[dict],
  slots: dict[str, dict],
  fibers_by_olt: dict[str, list[dict]],
  pon_sfp: dict[str, dict],
  ont_counts: dict[str, int],
  uplink_sfp: Optional[dict[str, list[dict]]] = None,
  ont_names_by_fiber: Optional[dict[str, list[str]]] = None,
  ont_info: Optional[dict[str, dict]] = None,
) -> None:
  log.info("[ASSEMBLE] building tables ...")

  device_rows = build_device(devices, slots)
  intf_rows = build_intf(devices, uplink_sfp or {})
  ponport_rows = build_ponport(fibers_by_olt, pon_sfp, ont_counts, devices)

  _save_jsonl(output_dir / "device.jsonl", device_rows)
  _save_jsonl(output_dir / "intf.jsonl", intf_rows)
  _save_jsonl(output_dir / "ponport.jsonl", ponport_rows)

  log.info("  device:  %d rows", len(device_rows))
  log.info("  intf:    %d rows", len(intf_rows))
  log.info("  ponport: %d rows", len(ponport_rows))

  if ont_names_by_fiber is not None and ont_info is not None:
    ont_rows = build_ont(fibers_by_olt, ont_names_by_fiber, ont_info, devices)
    _save_jsonl(output_dir / "ont.jsonl", ont_rows)
    log.info("  ont:     %d rows", len(ont_rows))
