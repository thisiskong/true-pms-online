"""Item 6: SLOT-INV — OLT configuration and board inventory via AC device-mf GET.

Note: The eqpt:slot-inventory IBN action is not present on firmware 25.6.
Equivalent data is available at the device-mf:device-mf intent-specific-data path.
"""

from pathlib import Path
from .client import AltiplanoClient, save

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
    lt_slots = [
        {
            "slot_name": b.get("slot-name"),
            "planned_type": b.get("planned-type"),
            "device_version": b.get("device-version"),
            "admin_state": b.get("admin-state"),
        }
        for b in boards
    ]
    return {
        "olt_name": olt_name,
        "swversion": d.get("device-version"),
        "hardware_type": hw_type,
        "olttype": HARDWARE_TYPE_TO_OLTTYPE.get(hw_type),
        "vendor": "Nokia",
        "ip_address": d.get("ip-address"),
        "transport_protocol": d.get("transport-protocol"),
        "lt_slots": lt_slots,
        "lt_slot_names": [b["slot_name"] for b in lt_slots],
    }


def run(client: AltiplanoClient, output_dir: Path, devices: list[dict]) -> dict[str, dict]:
    all_raw: dict[str, dict] = {}
    all_normalized: dict[str, dict] = {}

    for dev in devices:
        olt = dev["name"]
        print(f"[SLOT-INV] OLT={olt} ...")
        raw = fetch(client, olt)
        norm = normalize(raw, olt)
        all_raw[olt] = raw
        all_normalized[olt] = norm
        print(f"  sw={norm['swversion']} olttype={norm['olttype']} lt_slots={norm['lt_slot_names']}")

    save(output_dir, "06_slot_inv", all_raw, all_normalized)
    return all_normalized
