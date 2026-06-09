"""Item 4: ES-FIBER — list all fibers (PON ports) for each OLT."""

import re
from pathlib import Path
from .client import AltiplanoClient, save


ES_PATH = "/altiplano-indexsearch/intents/_search/"

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

DL_BW_MAP = {
  "gpon": 2488,
  "xgs-pon": 10240,
  "mpm-gpon-xgs": 10240,
}

UL_BW_MAP = {
  "gpon": 1244,
  "xgs-pon": 10240,
  "mpm-gpon-xgs": 10240,
}


def _parse_ponport(fiber_name: str, pon_id: str) -> str | None:
  """
  Derive ponport from pon-id field: 'LT1.PON16' -> '1-1-1-16'
  Falls back to parsing fiber name: 'SWOLT000044.L13P05' -> '1-1-13-5'
  """
  m = re.match(r"LT(\d+)\.PON(\d+)$", pon_id, re.IGNORECASE)
  if m:
    return f"1-1-{int(m.group(1))}-{int(m.group(2))}"
  m = re.match(r".*\.L(\d+)P(\d+)$", fiber_name, re.IGNORECASE)
  if m:
    return f"1-1-{int(m.group(1))}-{int(m.group(2))}"
  return None


def fetch(client: AltiplanoClient, olt_name: str) -> dict:
  body = {
    "from": "0",
    "size": "9999",
    "query": {
      "bool": {
        "filter": [{"term": {"intent-type": "fiber"}}],
        "must": [{"match": {"configuration.device-name": olt_name}}],
      }
    },
    "_source": ["target", "configuration", "required-network-state"],
  }
  return client.post(ES_PATH, body=body, es=True)


def normalize(raw: dict, olt_name: str) -> list[dict]:
  hits = raw.get("hits", {}).get("hits", [])
  fibers = []
  for hit in hits:
    src = hit.get("_source", {})
    target = src.get("target", {})
    cfg = src.get("configuration", {})
    fiber_name = target.get("fiber-name")
    xpon_raw = (cfg.get("xpon-type") or [""])[0]
    pon_id = (cfg.get("pon-id") or [""])[0]
    fibers.append({
      "olt_name": olt_name,
      "fiber_name": fiber_name,
      "ponport": _parse_ponport(fiber_name, pon_id) if fiber_name else None,
      "xpon_type_raw": xpon_raw,
      "iftype": XPON_TYPE_MAP.get(xpon_raw),
      "ifspeed": IFSPEED_MAP.get(xpon_raw),
      "l1_dl_max_bw": DL_BW_MAP.get(xpon_raw),
      "l1_ul_max_bw": UL_BW_MAP.get(xpon_raw),
      "pon_id": (cfg.get("pon-id") or [""])[0],
      "l1sp": (cfg.get("port-profile") or [""])[0],
      "required_network_state": src.get("required-network-state"),
    })
  return fibers


def run(client: AltiplanoClient, output_dir: Path, devices: list[dict]) -> dict[str, list[dict]]:
  all_fibers: dict[str, list[dict]] = {}
  all_raw: dict[str, dict] = {}

  for dev in devices:
    olt = dev["name"]
    print(f"[ES-FIBER] OLT={olt} ...")
    raw = fetch(client, olt)
    total = raw.get("hits", {}).get("total", {}).get("value", 0)
    fibers = normalize(raw, olt)
    all_raw[olt] = raw
    all_fibers[olt] = fibers
    print(f"  fibers: {total}")

  save(output_dir, "04_es_fiber", all_raw, {"fibers_by_olt": all_fibers, "total": sum(len(v) for v in all_fibers.values())})
  return all_fibers
