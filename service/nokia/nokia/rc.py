"""RC-Proxy (Altiplano AV service) — NT/control board and LLDP neighbor queries.

Reachable at the `-av` service prefix (confirmed against the testbed), not the
`-rcdeviceproxy` prefix documented elsewhere in this repo for the still-blocked
interface-level RC-INTF/RC-INTF-ONE items. Both queries below are per-item GETs
(one board component, or one uplink port) that gracefully skip a 404 rather
than treating it as an error, since not every component/port has data (e.g. an
absent standby NT card, or a port with no LLDP neighbor).

`device-df` chassis expose a single `Board` component; `device-mf` chassis
expose `Board-Nta`/`Board-Ntb` (active/standby NT control cards). Response
root is `ietf-hardware:component`, e.g.:
  {"ietf-hardware:component": {"model-name": "LMNT-A", "serial-num": "...",
    "state": {"admin-state": "unlocked", "oper-state": "enabled", ...}}}

LLDP neighbor data is queried per uplink port against the device's `.IHUB`
(uplink board) address, keyed by `port_no` (e.g. `"1/1/5"`, from
`uplink_sfp.normalize_uplinks()` — percent-encoded in the URL since it
contains `/`). Response root is `nokia-state:dest-mac`, whose `remote-system`
list holds the actual per-neighbor fields (`system-name`, `chassis-id`, etc.).
"""

import logging
import urllib.parse
from .client import AltiplanoClient

import requests

log = logging.getLogger(__name__)

_COMPONENTS_BY_INTENT_TYPE = {
  "device-df": ("Board",),
  "device-mf": ("Board-Nta", "Board-Ntb"),
}

_BOARD_ROLE = {
  "Board":      "CtrlBoard1",
  "Board-Nta":  "CtrlBoard1",
  "Board-Ntb":  "CtrlBoard2",
}


def _ibn_base(rel: str) -> str:
  return f"/{rel}-av/rest/restconf/data"


def boards_from_raw(raw: dict[str, dict]) -> list[dict]:
  """Parse {component: response} into board dicts for the boards list.

  Response root is `ietf-hardware:component`; board identity comes from
  `model-name`, operational status from the nested `state.oper-state`.
  """
  boards = []
  for component, resp in raw.items():
    comp = resp.get("ietf-hardware:component", {})
    state = comp.get("state", {})
    boards.append({
      "name":        component,
      "model-name":  comp.get("model-name"),
      "oper-status": state.get("oper-state"),
      "board-role":  _BOARD_ROLE.get(component),
    })
  return boards


def list_boards(client: AltiplanoClient, intent: dict) -> tuple[list[dict], dict[str, dict]]:
  """Query RC-Proxy hardware-state for the device's NT/control board(s).

  Returns (boards, raw): boards are parsed {"name", "model-name", "oper-status"}
  entries to append to the AC boards list; raw is {component: response} for
  archival so --phase=normalize can rebuild without hitting the network.
  """
  device = intent.get("target")
  intent_type = intent.get("intent-type")
  components = _COMPONENTS_BY_INTENT_TYPE.get(intent_type, ())

  raw: dict[str, dict] = {}
  for component in components:
    path = (f"{_ibn_base(client.rel)}/anv:device-manager/"
            f"anv-device-holders:device={device}/device-specific-data/"
            f"ietf-hardware:hardware-state/component={component}")
    try:
      raw[component] = client.get(path)
    except requests.exceptions.HTTPError as e:
      log.info("[RC] %s component=%s not available (%s)", device, component, e)

  boards = boards_from_raw(raw)
  log.info("[RC] %s boards=%s", device, [b["name"] for b in boards])
  return boards, raw


def lldp_from_raw(raw: dict[str, dict]) -> list[dict]:
  """Parse {port_no: response} into flat LLDP neighbor records.

  Response root is `nokia-state:dest-mac`, whose `remote-system` list holds
  the actual per-neighbor fields (a port can in principle have more than one
  remote-system entry, though in practice there's one).
  """
  records = []
  for port_no, resp in raw.items():
    dest_mac = resp.get("nokia-state:dest-mac", {})
    for entry in dest_mac.get("remote-system", []):
      records.append({
        "port_no":             port_no,
        "system-name":         entry.get("system-name"),
        "system-description":  entry.get("system-description"),
        "chassis-id":          entry.get("chassis-id"),
        "remote-port-id":      entry.get("remote-port-id"),
        "port-description":    entry.get("port-description"),
      })
  return records


def list_lldp(client: AltiplanoClient, device_name: str,
              port_nos: list[str]) -> tuple[list[dict], dict[str, dict]]:
  """Query RC-Proxy LLDP neighbor data for each of a device's uplink ports.

  Returns (records, raw): records are parsed LLDP neighbor dicts (one per
  port that has a neighbor); raw is {port_no: response} for archival so
  callers can rebuild offline without hitting the network.
  """
  raw: dict[str, dict] = {}
  for port_no in port_nos:
    port_no_enc = urllib.parse.quote(port_no, safe="")
    path = (f"{_ibn_base(client.rel)}/anv:device-manager/"
            f"anv-device-holders:device={device_name}.IHUB/device-specific-data/"
            f"nokia-state:state/port={port_no_enc}/ethernet/lldp/dest-mac=nearest-bridge")
    try:
      raw[port_no] = client.get(path)
    except requests.exceptions.HTTPError as e:
      log.info("[RC] %s port=%s no LLDP neighbor (%s)", device_name, port_no, e)

  records = lldp_from_raw(raw)
  log.info("[RC] %s lldp neighbors=%d", device_name, len(records))
  return records, raw
