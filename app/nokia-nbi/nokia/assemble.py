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

def build_intf(devices: list[dict]) -> list[dict]:
  ts = _now()
  rows = []
  for dev in devices:
    # One placeholder row per OLT — all RC-Proxy fields are NotImplement.
    # Will be replaced with real rows once RC-INTF (item 9) is unblocked.
    rows.append({
      # --- available from device table ---
      "device_ip":        dev.get("ip"),
      "device_name":      dev.get("name"),
      "iftype":           "ethernetCsmacd",   # fixed for all uplink ports
      "sys_pollstatus":   1,
      "usr_pollstatus":   1,
      "last_modify_by":   "nokia-discovery",
      "last_modify_at":   ts,
      "lastseen":         ts,
      "first":            ts,
      # --- NotImplement: available via RC-INTF (item 9 — RC-Proxy blocked) ---
      "id":               NI,   # compose: {device.id}.{ifindex}
      "device_id":        NI,   # FK from device.id
      "ifname":           NI,   # RC-Proxy interface[].name
      "ifdescr":          NI,   # RC-Proxy interface[].description
      "ifspeed":          NI,   # RC-Proxy interface[].speed
      "ifadmin":          NI,   # RC-Proxy interface[].admin-status
      "ifoper":           NI,   # RC-Proxy interface[].oper-status
      "ifindex":          NI,   # RC-Proxy interface[].if-index
      "ifphyaddr":        NI,   # RC-Proxy interface[].phys-address
      "ifalias":          NI,   # RC-Proxy interface[].description
      "ifconn":           NI,   # derived from ifoper
      "name":             NI,   # compose: {device_name}:{ifname}
      # --- NotImplement: available via UPLINK-SFP (item 7 — eqpt action blocked) ---
      "moduleclass":      NI,   # eqpt:show-uplink-sfp-diag-inv → module-class
      "vendorpn":         NI,   # eqpt:show-uplink-sfp-diag-inv → part-number
      "mediatype":        NI,   # derived from moduleclass (SM/MM)
      # --- NotSupported: not available from Nokia NBI ---
      "altname":          NS,   # optional alternate name — not in Altiplano
      "dstport":          NS,   # neighbor port — LLDP or manual
      "dstsite":          NS,   # neighbor site — manual mapping
      "dsttype":          NS,   # neighbor device type — manual mapping
      "dstname":          NS,   # neighbor device name — LLDP or manual
      "dstsite2":         NS,   # secondary neighbor site — manual
      "dsttype2":         NS,   # secondary neighbor device type — manual
      "remdstsite":       NS,   # remote destination site — manual
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
        # --- NotImplement: available via RC-INTF-ONE (item 10 — RC-Proxy blocked) ---
        "id":               NI,   # compose: {device.id}.{ifindex}
        "device_id":        NI,   # FK from device.id
        "ifadmin":          NI,   # RC-Proxy interface.admin-status
        "ifoper":           NI,   # RC-Proxy interface.oper-status
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
) -> None:
  print("[ASSEMBLE] building tables ...")

  device_rows = build_device(devices, slots)
  intf_rows = build_intf(devices)
  ponport_rows = build_ponport(fibers_by_olt, pon_sfp, ont_counts, devices)

  _save_jsonl(output_dir / "device.jsonl", device_rows)
  _save_jsonl(output_dir / "intf.jsonl", intf_rows)
  _save_jsonl(output_dir / "ponport.jsonl", ponport_rows)

  print(f"  device:  {len(device_rows)} rows")
  print(f"  intf:    {len(intf_rows)} rows (placeholder per OLT — RC-Proxy blocked)")
  print(f"  ponport: {len(ponport_rows)} rows")
