"""Item 9: AC-ONT — per-ONT operational info via show-ont-info action."""

import json
import logging
from pathlib import Path
from .client import AltiplanoClient

log = logging.getLogger(__name__)


def _ac_path(rel: str, ont_name: str) -> str:
  return (
    f"/{rel}-ac/rest/restconf/data/ibn:ibn"
    f"/intent={ont_name},ont"
    f"/intent-specific-data/ont-action:show-ont-info"
  )


def fetch(client: AltiplanoClient, ont_name: str) -> dict:
  return client.get(_ac_path(client.rel, ont_name))


def normalize(raw: dict, ont_name: str) -> dict:
  # Response may be wrapped under various keys depending on Altiplano version.
  # Try common paths; fall back to raw dict inspection.
  info = (
    raw.get("ont-action:show-ont-info")
    or raw.get("show-ont-info")
    or raw
  )
  ont_data = info.get("ont", info) if isinstance(info, dict) else {}

  def _first(val):
    """Unwrap single-element list; return None for empty/missing."""
    if isinstance(val, list):
      return val[0] if val else None
    return val

  return {
    "ont_name":      ont_name,
    "oper_state":    _first(ont_data.get("oper-state")),
    "admin_state":   _first(ont_data.get("admin-state")),
    "rx_signal":     _first(ont_data.get("rx-signal-level")),   # dBm (RxPwr)
    "tx_signal":     _first(ont_data.get("tx-signal-level")),   # dBm (TxPwr)
    "distance":      _first(ont_data.get("distance")),          # metres
    "serial_number": _first(ont_data.get("serial-number")),
    "hw_type":       _first(ont_data.get("hardware-type") or ont_data.get("ont-type")),
    "sw_version":    _first(ont_data.get("sw-version") or ont_data.get("software-version")),
  }


def run(
  client: AltiplanoClient,
  output_dir: Path,
  ont_names_by_fiber: dict[str, list[str]],
) -> dict[str, dict]:
  """Fetch show-ont-info for every ONT; returns ont_name -> normalized dict."""
  all_raw: dict[str, dict] = {}
  ont_info: dict[str, dict] = {}

  all_names: list[str] = [
    name
    for names in ont_names_by_fiber.values()
    for name in names
  ]
  total = len(all_names)
  log.info("[AC-ONT] fetching show-ont-info for %d ONTs ...", total)

  for i, ont_name in enumerate(all_names, 1):
    if i % 50 == 0 or i == total:
      log.info("  %d/%d", i, total)
    try:
      raw = fetch(client, ont_name)
      all_raw[ont_name] = raw
      ont_info[ont_name] = normalize(raw, ont_name)
    except Exception as exc:
      log.warning("[AC-ONT] %s: %s", ont_name, exc)
      ont_info[ont_name] = {"ont_name": ont_name, "error": str(exc)}

  output_dir.mkdir(parents=True, exist_ok=True)
  raw_path = output_dir / "09_ac_ont_raw.json"
  norm_path = output_dir / "09_ac_ont_normalized.json"
  raw_path.write_text(json.dumps(all_raw, indent=2), encoding="utf-8")
  norm_path.write_text(json.dumps(list(ont_info.values()), indent=2), encoding="utf-8")
  log.info("  saved: 09_ac_ont_raw.json + 09_ac_ont_normalized.json")

  return ont_info
