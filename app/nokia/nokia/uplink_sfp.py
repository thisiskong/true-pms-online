"""Item 7: UPLINK-SFP — list uplink connections via ES, then fetch SFP diagnostics/inventory."""

import logging
from pathlib import Path
from .client import AltiplanoClient, save

log = logging.getLogger(__name__)

ES_PATH = "/altiplano-indexsearch/intents/_search/"
SFP_ACTION = "sfp-status:show-sfp-diagnostics-and-inventory"


def fetch_uplinks(client: AltiplanoClient, olt_name: str) -> dict:
  body = {
    "from": "0",
    "size": "9999",
    "query": {
      "bool": {
        "filter": [{"term": {"intent-type": "uplink-connection"}}],
        "must": [{"match": {"target.device-name": olt_name}}],
      }
    },
    "_source": ["target", "configuration"],
  }
  return client.post(ES_PATH, body=body, es=True)


def fetch_sfp(client: AltiplanoClient, rel: str, uplink_name: str, port_id: str) -> dict:
  path = f"/{rel}-ac/rest/restconf/data/ibn:ibn/intent={uplink_name},uplink-connection/intent-specific-data/{SFP_ACTION}"
  body = {"sfp-status:input": {"entity": port_id}}
  return client.post(path, body=body)


def normalize_uplinks(raw: dict, olt_name: str) -> list[dict]:
  hits = raw.get("hits", {}).get("hits", [])
  uplinks = []
  for hit in hits:
    src = hit.get("_source", {})
    cfg = src.get("configuration", {})
    target = src.get("target", {})
    port_ids = cfg.get("port-id", [])
    uplinks.append({
      "olt_name": olt_name,
      "uplink_name": target.get("device-name", olt_name),
      "port_ids": port_ids,
      "agg_system_name": (cfg.get("agg-system-name") or [""])[0],
      "l1_profile": (cfg.get("l1-profile") or [""])[0],
    })
  return uplinks


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
    log.info("[UPLINK-SFP] OLT=%s — fetching uplink-connection intents ...", olt)
    ul_raw = fetch_uplinks(client, olt)
    all_uplinks_raw[olt] = ul_raw
    uplinks = normalize_uplinks(ul_raw, olt)
    log.info("  uplink intents: %d", len(uplinks))

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
       {"uplinks_es": all_uplinks_raw, "sfp_calls": all_sfp_raw},
       {"uplink_sfp_by_olt": result})
  return result
