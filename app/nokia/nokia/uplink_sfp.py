"""Item 7: UPLINK-SFP — list uplink connections via AC, then fetch SFP diagnostics/inventory."""

import logging
from pathlib import Path
from .client import AltiplanoClient, save
from . import ac

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
  isd = intent.get("intent-specific-data", {})
  ports = isd.get("uplink-connection:uplink-connection", {}).get("uplink-ports", [])
  if not ports:
    return []
  return [{
    "olt_name": olt_name,
    "uplink_name": olt_name,
    "port_ids": [p.get("port-id") for p in ports if p.get("port-id")],
    "agg_system_name": (ports[0].get("agg-system-name") or ""),
    "l1_profile": (ports[0].get("l1-profile") or ""),
  }]


def normalize_sfp(sfp_raw: dict, uplink_name: str, port_id: str) -> dict:
  out = sfp_raw.get("sfp-status:output", {})
  inventory = (out.get("inventory") or [{}])[0]
  # sfp-status list: first entry has temp/voltage, lane entries have tx/rx power
  sfp_entries = out.get("sfp-status") or []
  port_status = next((s for s in sfp_entries if s.get("name") == port_id), {})
  lane_status = next((s for s in sfp_entries if ":lane-" in s.get("name", "")), {})
  tca_entries = out.get("tca-status") or []
  tca_lane = next((t for t in tca_entries if ":lane-" in t.get("name", "")), {})
  return {
    "uplink_name": uplink_name,
    "port_id": port_id,
    "oper_state": inventory.get("oper-status"),
    "admin_state": inventory.get("admin-status"),
    "part_number": (inventory.get("part-number") or "").strip(),
    "serial_number": (inventory.get("serial-number") or "").strip(),
    "manufacture_date": inventory.get("manufacture-date"),
    "wave_length": inventory.get("wave-length"),
    "tx_power": lane_status.get("tx-power"),
    "rx_power": lane_status.get("rx-power"),
    "sfp_temp": port_status.get("sfp-temp"),
    "supply_voltage": port_status.get("supply-voltage"),
    "bias_current": lane_status.get("bias-current"),
    "tca_tx_power": tca_lane.get("tx-power"),
    "tca_rx_power": tca_lane.get("rx-power"),
  }


def run(client: AltiplanoClient, output_dir: Path, devices: list[dict]) -> dict[str, list[dict]]:
  all_uplinks_raw: dict = {}
  all_sfp_raw: dict = {}
  result: dict[str, list[dict]] = {}

  for dev in devices:
    olt = dev["name"]
    log.info("[UPLINK-SFP] OLT=%s — fetching uplink-connection intent ...", olt)
    ul_raw = fetch_uplink(client, olt)
    all_uplinks_raw[olt] = ul_raw
    uplinks = normalize_uplinks(ul_raw, olt)
    log.info("  uplink ports: %d", sum(len(u["port_ids"]) for u in uplinks))

    sfp_list = []
    all_sfp_raw[olt] = {}
    for ul in uplinks:
      ul_name = ul["uplink_name"]
      for port_id in ul["port_ids"]:
        log.info("  fetching SFP: intent=%s port=%s", ul_name, port_id)
        try:
          sfp_raw = fetch_sfp(client, client.rel, ul_name, port_id)
          all_sfp_raw[olt][f"{ul_name}:{port_id}"] = sfp_raw
          sfp_list.append(normalize_sfp(sfp_raw, ul_name, port_id))
        except Exception as e:
          log.warning("  [WARN] %s", e)
          all_sfp_raw[olt][f"{ul_name}:{port_id}"] = {"error": str(e)}
          sfp_list.append({"uplink_name": ul_name, "port_id": port_id, "error": str(e)})
    result[olt] = sfp_list

  save(output_dir, "07_uplink_sfp",
       {"uplinks_ac": all_uplinks_raw, "sfp_calls": all_sfp_raw},
       {"uplink_sfp_by_olt": result})
  return result
