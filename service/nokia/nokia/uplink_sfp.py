"""Item 7: UPLINK-SFP — list uplink connections via AC, then fetch SFP diagnostics/inventory."""

import json
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Optional
from .client import AltiplanoClient, save
from . import ac
from . import rc

log = logging.getLogger(__name__)

UPLINK_INTENT_TYPE = "uplink-connection"
SFP_ACTION = "sfp-status:show-sfp-diagnostics-and-inventory"


def fetch_uplink(client: AltiplanoClient, olt_name: str) -> dict:
  return ac.get_intent(client, olt_name, UPLINK_INTENT_TYPE)


def fetch_sfp(client: AltiplanoClient, rel: str, uplink_name: str, port_id: str) -> dict:
  path = f"/{rel}-ac/rest/restconf/data/ibn:ibn/intent={uplink_name},uplink-connection/intent-specific-data/{SFP_ACTION}"
  body = {"sfp-status:input": {"entity": port_id}}
  return client.post(path, body=body)


def normalize_uplinks(intent: dict, olt_name: str) -> list[dict]:
  uplinks = []
  uplink_ports_descriptions = dict()
  uplink_ports = intent.get("intent-specific-data", {}).get("uplink-connection:uplink-connection", {}).get("uplink-ports", [])
  for port in uplink_ports:
    port_id = port.get("port-id")
    port_description = port.get("port-description")
    uplink_ports_descriptions[port_id] = port_description

  topologies = intent.get("topology", [])
  for topo in topologies:
    objects     = topo.get("object", [])
    for obj in objects:
      object_name = obj.get("object-name")
      object_id   = urllib.parse.unquote(obj.get("relative-object-id"))
      object_type = obj.get("object-type")
      admin_state = obj.get("admin-state")
      oper_state  = obj.get("oper-state")
      # log.info(f"{olt_name}|{object_name}|{object_id}|{object_type}|{admin_state}|{oper_state}")

      if "anv-device-holders:device-manager/device" == object_type:
        # object_name = port:RET02002G00.IHUB:nokia-state:state/1
        tokens = object_name.split(":")
        if len(tokens) == 4 and tokens[0] == "port":
          # object_id = anv:total-uplink-port:{##objectType=nokia-state:state/port=1/1/5##Name=nt-a:xfp:1##speed=10000}
          m = re.match(r'.*\/port=(.*)##Name=(.*)##speed=(\d+)', object_id)
          if m:
            port_no = m.group(1)
            port_id = m.group(2)
            speed_bps = int(m.group(3)) * 1_000_000
            port_description = uplink_ports_descriptions.get(port_id)
            log.info(f"{olt_name}|{object_id}|{port_no}|{port_id}|{port_description}|{speed_bps}|{admin_state}|{oper_state}")
            uplinks.append({
              "olt_name": olt_name,
              "port_no": port_no,
              "port_id": port_id,
              "admin_state": admin_state,
              "oper_state": oper_state,
              "speed_bps": speed_bps,
              "port_description": port_description,
            })
  return uplinks


def normalize_sfp(sfp_raw: dict, olt_name: str, port_id: str, ul, lldp: Optional[dict] = None) -> dict:
  out = sfp_raw.get("sfp-status:output", {})
  inventory = (out.get("inventory") or [{}])[0]
  return {
    "olt_name": olt_name,
    "port_id": port_id,
    "port_no": ul["port_no"],
    "port_description": ul.get("port_description"),
    "speed_bps": ul["speed_bps"],
    "oper_state": ul["oper_state"],
    "admin_state": ul["admin_state"],
    "part_number": (inventory.get("part-number") or "").strip(),
    "serial_number": (inventory.get("serial-number") or "").strip(),
    "manufacture_date": inventory.get("manufacture-date"),
    "wave_length": inventory.get("wave-length"),
    "lldp_sysname": (lldp or {}).get("system-name"),
    "lldp_remote_port_id": (lldp or {}).get("remote-port-id"),
  }


def run(client: AltiplanoClient, output_dir: Path, devices: list[dict]) -> dict[str, list[dict]]:
  all_uplinks_raw: dict = {}
  all_sfp_raw: dict = {}
  all_lldp_raw: dict = {}
  result: dict[str, list[dict]] = {}

  for dev in devices:
    olt = dev["name"]
    log.info("[UPLINK-SFP] OLT=%s — fetching uplink-connection intent ...", olt)
    ul_raw = fetch_uplink(client, olt)
    all_uplinks_raw[olt] = ul_raw
    uplinks = normalize_uplinks(ul_raw, olt)
    log.info("  uplink ports: %d", len(uplinks))

    lldp_records, lldp_raw = rc.list_lldp(client, olt, [ul["port_no"] for ul in uplinks])
    all_lldp_raw[olt] = lldp_raw
    lldp_by_port = {r["port_no"]: r for r in lldp_records}

    sfp_list = []
    all_sfp_raw[olt] = {}
    for ul in uplinks:
      olt_name = ul["olt_name"]
      port_id  = ul["port_id"]
      log.info("  fetching SFP: intent=%s port=%s", olt_name, port_id)
      try:
        sfp_raw = fetch_sfp(client, client.rel, olt_name, port_id)
        all_sfp_raw[olt][f"{olt_name}:{port_id}"] = sfp_raw
        sfp_list.append(normalize_sfp(sfp_raw, olt_name, port_id, ul, lldp_by_port.get(ul["port_no"])))
      except Exception as e:
        log.warning("  [WARN] %s", e)
        all_sfp_raw[olt][f"{olt_name}:{port_id}"] = {"error": str(e)}
        sfp_list.append({"olt_name": olt_name, "port_id": port_id, "error": str(e)})

    result[olt] = sfp_list

  save(output_dir, "07_uplink_sfp",
       {"uplinks_ac": all_uplinks_raw, "sfp_calls": all_sfp_raw, "lldp_calls": all_lldp_raw},
       {"uplink_sfp_by_olt": result})
  return result


def run_normalize(output_dir: Path, devices: list[dict]) -> dict[str, list[dict]]:
  """Rebuild uplink_sfp_by_olt from 07_uplink_sfp_raw.json — no network."""
  raw = json.loads((output_dir / "07_uplink_sfp_raw.json").read_text())
  all_uplinks_raw = raw["uplinks_ac"]
  all_sfp_raw = raw["sfp_calls"]
  all_lldp_raw = raw.get("lldp_calls", {})

  result: dict[str, list[dict]] = {}

  for dev in devices:
    olt = dev["name"]

    ul_raw = all_uplinks_raw.get(olt)
    if ul_raw is None:
      log.warning("[UPLINK-SFP] no raw uplink data for %s, skipping", olt)
      continue

    uplinks = normalize_uplinks(ul_raw, olt)
    lldp_by_port = {r["port_no"]: r for r in rc.lldp_from_raw(all_lldp_raw.get(olt, {}))}

    sfp_list = []
    for ul in uplinks:
      olt_name = ul["olt_name"]
      port_id  = ul["port_id"]
      key = f"{olt_name}:{port_id}"
      sfp_raw = all_sfp_raw.get(olt, {}).get(key)
      if sfp_raw is None:
        log.warning("[UPLINK-SFP] no raw SFP data for %s, skipping", key)
        continue
      if isinstance(sfp_raw, dict) and "error" in sfp_raw:
        sfp_list.append({"olt_name": olt_name, "port_id": port_id, "error": sfp_raw["error"]})
      else:
        sfp_list.append(normalize_sfp(sfp_raw, olt_name, port_id, ul, lldp_by_port.get(ul["port_no"])))
    result[olt] = sfp_list

  save(output_dir, "07_uplink_sfp",
       {"uplinks_ac": all_uplinks_raw, "sfp_calls": all_sfp_raw, "lldp_calls": all_lldp_raw},
       {"uplink_sfp_by_olt": result})
  return result
