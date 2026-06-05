"""Item 3: ES-DEVICE — list all OLTs from Elasticsearch intent index."""

from pathlib import Path
from .client import AltiplanoClient, save


ES_PATH = "/altiplano-indexsearch/intents/_search/"

HARDWARE_TYPE_TO_OLTTYPE = {
    "LS-MF-LANT-A": "MF-2",
    "LS-MF-LMNT-A": "MF-2",
    "LS-DF-CFXR-H": "DF-16GM",
}


def fetch(client: AltiplanoClient) -> dict:
    body = {
        "from": "0",
        "size": "9999",
        "query": {
            "bool": {
                "filter": [{"term": {"intent-type": "device-mf"}}]
            }
        },
        "_source": ["target", "configuration", "required-network-state", "state"],
    }
    return client.post(ES_PATH, body=body, es=True)


def normalize(raw: dict) -> list[dict]:
    hits = raw.get("hits", {}).get("hits", [])
    devices = []
    for hit in hits:
        src = hit.get("_source", {})
        target = src.get("target", {})
        cfg = src.get("configuration", {})
        hw_type = (cfg.get("hardware-type") or [""])[0]
        devices.append({
            "name": target.get("device-name"),
            "ip": (cfg.get("ip-address") or [""])[0],
            "swversion": (cfg.get("device-version") or [""])[0],
            "descr": hw_type,
            "olttype": HARDWARE_TYPE_TO_OLTTYPE.get(hw_type),
            "vendor": "Nokia",
            "sys_pollstatus": 1 if src.get("required-network-state") == "active" else 0,
        })
    return devices


def run(client: AltiplanoClient, output_dir: Path) -> list[dict]:
    print("[ES-DEVICE] fetching OLT list ...")
    raw = fetch(client)
    total = raw.get("hits", {}).get("total", {}).get("value", 0)
    print(f"  total hits: {total}")
    normalized = normalize(raw)
    save(output_dir, "03_es_device", raw, {"devices": normalized, "count": len(normalized)})
    print(f"  devices found: {len(normalized)}")
    return normalized
