"""Assemble device, intf, and ponport rows from collected API data and save as JSONL.

Field value conventions:
  "NotSupported"  — field has no equivalent in Nokia Altiplano NBI (requires LLDP, SNMP, or manual mapping)
  "NotImplement"  — field is available from Nokia API but not yet collected (blocked or pending implementation)
"""

import json
from datetime import datetime, timezone
from pathlib import Path

NS = "NotSupported"   # not available from Nokia NBI
NI = "NotImplement"   # available from Nokia NBI but not yet implemented/unblocked


def _now() -> str:
  return datetime.now(timezone.utc).isoformat()


def _save_jsonl(path: Path, rows: list[dict]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("w", encoding="utf-8") as f:
    for row in rows:
      f.write(json.dumps(row, ensure_ascii=False) + "\n")
  print(f"  saved: {path.name} ({len(rows)} rows)")


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
      "olttype":          slot.get("olttype") or dev.get("olttype"),
      "swversion":        slot.get("swversion") or dev.get("swversion"),
      "transport_protocol": slot.get("transport_protocol"),
      "lt_slots":         slot.get("lt_slot_names", []),
      "agent":            "altiplano",
      "sys_pollstatus":   dev.get("sys_pollstatus", 1),
      "usr_pollstatus":   1,
      "pollint":          86400,
      "last_modify_by":   "nokia-discovery",
      "last_modify_at":   ts,
      "lastseen":         ts,
      "first":            ts,
      # --- NotImplement: available via eqpt action (blocked on fw 25.6) ---
      "model":            NI,   # eqpt:slot-inventory → Chassis.model
      "chassisid":        NI,   # eqpt:slot-inventory → Chassis.serial-num
      "pn":               NI,   # eqpt:slot-inventory → Chassis.code
      # --- NotSupported: not available from Nokia NBI ---
      "network":          NS,   # static topology config
      "region":           NS,   # static site mapping
      "province":         NS,   # static site mapping
      "sitename":         NS,   # static site mapping
      "latitude":         NS,   # static site coordinates
      "longitude":        NS,   # static site coordinates
      "sysuptime":        NS,   # SNMP OID 1.3.6.1.2.1.1.3.0 only
      "community":        NS,   # SNMP community string — external credential
      "dn":               NS,   # domain name — not in Altiplano
      "hop":              NS,   # network hop count — not in Altiplano
      "rn":               NS,   # ring node ID — static topology
      "ringid":           NS,   # ring ID — static topology
      "ringtopo":         NS,   # ring topology type — static topology
      "topology":         NS,   # static topology config
      "uplink_ip1":       NS,   # upstream device IP — LLDP or manual
      "uplink_ip2":       NS,   # secondary uplink IP — LLDP or manual
      "uplink_model1":    NS,   # upstream device model — LLDP or manual
      "uplink_model2":    NS,   # secondary uplink model — LLDP or manual
      "uplink_site1":     NS,   # upstream site — manual mapping
      "uplink_site2":     NS,   # secondary uplink site — manual mapping
      "a_homing_id":      NS,   # aggregation homing ID — topology config
      "a_homing_site":    NS,   # aggregation homing site — topology config
      "b_homing_id":      NS,   # backup homing ID — topology config
      "b_homing_site":    NS,   # backup homing site — topology config
      "c_homing_id":      NS,   # topology config
      "c_homing_site":    NS,   # topology config
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


def _port_moduleclass(port_id: str) -> str | None:
  """Derive moduleclass from port_id token e.g. 'nt-a:xfp:1' -> '10GE-XFP'."""
  for token, cls in _PORT_TYPE_TO_MODULECLASS.items():
    if f":{token}:" in port_id or port_id.endswith(f":{token}"):
      return cls
  return None


def _vendorpn(part_number: str) -> str | None:
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
      pn = _vendorpn(sfp.get("part_number", ""))
      wave = (sfp.get("wave_length") or "").strip().lstrip("0") or None
      oper = sfp.get("oper_state")
      admin = sfp.get("admin_state")
      rows.append({
        # --- available from ES-DEVICE ---
        "device_ip":        dev.get("ip"),
        "device_name":      olt,
        "iftype":           "ethernetCsmacd",
        "sys_pollstatus":   1,
        "usr_pollstatus":   1,
        "last_modify_by":   "nokia-discovery",
        "last_modify_at":   ts,
        "lastseen":         ts,
        "first":            ts,
        # --- available from UPLINK-SFP (item 7) ---
        "ifname":           port_id,
        "ifdescr":          port_id,
        "name":             f"{olt}:{port_id}",
        "ifadmin":          "down" if admin == "disable" else "up" if admin else NI,
        "ifoper":           oper if oper and oper != "-" else NI,
        "moduleclass":      _port_moduleclass(port_id),
        "vendorpn":         pn,
        "mediatype":        _WAVELENGTH_TO_MEDIATYPE.get(wave) if wave else NI,
        # --- NotImplement: available via RC-INTF (item 9 — RC-Proxy blocked) ---
        "id":               NI,   # composite {device.id}.{ifindex}
        "device_id":        NI,   # FK from device table
        "ifspeed":          NI,   # RC-Proxy interface[].speed
        "ifindex":          NI,   # RC-Proxy interface[].if-index
        "ifphyaddr":        NI,   # RC-Proxy interface[].phys-address (MAC)
        "ifalias":          NI,   # RC-Proxy interface[].description
        "ifconn":           NI,   # derived from ifoper
        # --- NotSupported: not available from Nokia NBI ---
        "altname":          NS,
        "dstport":          NS,
        "dstsite":          NS,
        "dsttype":          NS,
        "dstname":          NS,
        "dstsite2":         NS,
        "dsttype2":         NS,
        "remdstsite":       NS,
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
        "ifname":           fname,
        "ifdescr":          fname,
        "ponport":          fiber.get("ponport"),
        "iftype":           fiber.get("iftype"),
        "ifspeed":          fiber.get("ifspeed"),
        "l1_dl_max_bw":     fiber.get("l1_dl_max_bw"),
        "l1_ul_max_bw":     fiber.get("l1_ul_max_bw"),
        "l1sp":             fiber.get("l1sp"),
        "xpon_type":        fiber.get("xpon_type_raw"),
        "pon_id":           fiber.get("pon_id"),
        "name":             f"{olt}:{fiber.get('ponport')}",
        # --- available from PON-SFP (item 8) ---
        "moduleclass":      sfp.get("moduleclass"),
        "vendorpn":         sfp.get("vendorpn"),
        "model_name":       sfp.get("model_name"),
        # --- available from ES-ONT (item 5) ---
        "ifconn":           ont_counts.get(fname, 0),
        # --- available (defaults) ---
        "sys_pollstatus":   1,
        "usr_pollstatus":   1,
        "last_modify_by":   "nokia-discovery",
        "last_modify_at":   ts,
        "lastseen":         ts,
        "first":            ts,
        # --- available from PON-SFP (fiber:fiber AC) and ES-FIBER ---
        "ifadmin":          "down" if sfp.get("admin_state") == "locked" else "up",
        "ifoper":           "up" if fiber.get("required_network_state") == "active" else "down" if fiber.get("required_network_state") else NI,
        # --- NotImplement: available via RC-INTF-ONE (item 10 — RC-Proxy blocked) ---
        "id":               NI,   # compose: {device.id}.{ifindex}
        "device_id":        NI,   # FK from device.id
        "ifindex":          NI,   # RC-Proxy interface.if-index
        # --- NotImplement: optional, requires PON utilization monitoring enabled ---
        "dl_bw_remaining":  NI,   # OpenTSDB PON utilization — requires §4.2.15 enabled
        "ul_bw_remaining":  NI,   # OpenTSDB PON utilization — requires §4.2.15 enabled
        # --- NotSupported: not applicable for PON ports ---
        "ifphyaddr":        NS,   # PON ports have no MAC address
        "ifalias":          NS,   # not applicable for PON
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
  uplink_sfp: dict[str, list[dict]] | None = None,
) -> None:
  print("[ASSEMBLE] building tables ...")

  device_rows = build_device(devices, slots)
  intf_rows = build_intf(devices, uplink_sfp or {})
  ponport_rows = build_ponport(fibers_by_olt, pon_sfp, ont_counts, devices)

  _save_jsonl(output_dir / "device.jsonl", device_rows)
  _save_jsonl(output_dir / "intf.jsonl", intf_rows)
  _save_jsonl(output_dir / "ponport.jsonl", ponport_rows)

  print(f"  device:  {len(device_rows)} rows")
  print(f"  intf:    {len(intf_rows)} rows")
  print(f"  ponport: {len(ponport_rows)} rows")
