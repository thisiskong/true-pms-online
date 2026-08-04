"""Map discovery JSONL output to Device/Interface struct format.
Mirrors the Go structs:
  Device     — device.jsonl + slot_inv boards
  Interface  — intf.jsonl (uplink ports) + ponport.jsonl (PON ports)

NotSupported/NotImplement sentinel values from assemble.py are preserved as-is.
Numeric fields that carry sentinels are left as the sentinel string rather than
coerced to 0 so callers can distinguish "unknown" from "zero".
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _int_or(v, default=None):
  try:
    return int(v)
  except (TypeError, ValueError):
    return default


def _float_or(v, default=0.0):
  try:
    return float(v)
  except (TypeError, ValueError):
    return default


def _str(v):
  if v is None:
    return None
  return str(v)


def _load_jsonl(path: Path) -> list[dict]:
  if not path.exists():
    return []
  return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Interface — from intf.jsonl (uplink ethernet port)
# ---------------------------------------------------------------------------

def _map_intf(row: dict) -> dict:
  return {
    "IfIndex":       _str(row.get("ifindex")),
    "IfName":        _str(row.get("ifname")),
    "IfSpeed":       _int_or(row.get("ifspeed")),
    "IfAdmin":       _str(row.get("ifadmin")),
    "IfOper":        _str(row.get("ifoper")),
    "IfDescr":       _str(row.get("ifdescr")),
    "IfAlias":       _str(row.get("ifdescr")),
    "IfTopology":    None,
    "IfDstIp":       None,
    "IfType":        _str(row.get("iftype")),
    "IfPhyAddr":     None,
    "IfConn":        _int_or(row.get("ifconn")),
    "Name":          None,
    "DstName":       _str(row.get("lldp_sysname")),
    "DstPort":       _str(row.get("lldp_remote_port_id")),
    "DstSite":       _str(row.get("dstsite")),
    "DstType":       _str(row.get("dsttype")),
    "RemDstSite":    _str(row.get("remdstsite")),
    "MediaType":     None,
    "PollStatus":    None,
    "PonPort":       None,
    "Save":          True,
    "DstSite2":      None,
    "DstType2":      None,
    # Service API (uplink has no L1 fields)
    "L1_SPLT":          None,
    "L1_DL_MAX_BW":     None,
    "L1_UL_MAX_BW":     None,
    "DL_BW_REMAINING":  None,
    "UL_BW_REMAINING":  None,
    # FTTx Optical Module
    "VendorPn":      _str(row.get("vendorpn")),
    "ModuleClass":   _str(row.get("moduleclass")),
    # CR2026
    "AltName":       _str(row.get("altname")),
    "NokiaDstSite":  None,
  }


# ---------------------------------------------------------------------------
# Interface — from ponport.jsonl (PON port)
# ---------------------------------------------------------------------------

def _map_ponport(row: dict) -> dict:
  return {
    "IfIndex":       _str(row.get("pon_id")),
    "IfName":        _str(row.get("ifname")),
    "IfSpeed":       _int_or(row.get("ifspeed")),
    "IfAdmin":       _str(row.get("ifadmin")),
    "IfOper":        _str(row.get("ifoper")),
    "IfDescr":       _str(row.get("ifdescr")),
    "IfAlias":       _str(row.get("ifdescr")),
    "IfTopology":    None,
    "IfDstIp":       None,
    "IfType":        _str(row.get("iftype")),
    "IfPhyAddr":     None,
    "IfConn":        None,
    "Name":          None,
    "DstName":       None,
    "DstPort":       None,
    "DstSite":       None,
    "DstType":       None,
    "RemDstSite":    None,
    "MediaType":     None,
    "PollStatus":    None,
    "PonPort":       _str(row.get("ponport")),
    "Save":          True,
    "DstSite2":      None,
    "DstType2":      None,
    # Service API
    "L1_SPLT":          None,
    "L1_DL_MAX_BW":     None,
    "L1_UL_MAX_BW":     None,
    "DL_BW_REMAINING":  None,
    "UL_BW_REMAINING":  None,
    # FTTx Optical Module
    "VendorPn":      _str(row.get("vendorpn")),
    "ModuleClass":   _str(row.get("moduleclass")),
    # CR2026
    "AltName":       None,
    "NokiaDstSite":  None,
  }


# ---------------------------------------------------------------------------
# Board — from slot_inv normalized data
# ---------------------------------------------------------------------------

def _map_board(board: dict) -> dict:
  return {
    "BoardName":   _str(board.get("name")),
    "BoardType":   _str(board.get("model-name")),
    "BoardRole":   _str(board.get("board-role")),
    "OperStatus":  _str(board.get("oper-status")),
  }


# ---------------------------------------------------------------------------
# Device — from device.jsonl, assembled with interfaces and boards
# ---------------------------------------------------------------------------

def _map_device(
  row: dict,
  interfaces: list[dict],
  boards: list[dict],
) -> dict:
  return {
    "DeviceId":         None, # _int_or(row.get("id")),
    "DeviceIp":         _str(row.get("ip")),
    "ChassisId":        _str(row.get("name")),
    "SysName":          _str(row.get("name")),
    "SysDescr":         _str(row.get("descr")),
    "SysObjectID":      None,                        # not available from Nokia NBI
    "Network":          "FTTx",
    "Topology":         "OLT",
    "Community":        None,
    "Agent":            None,
    "DiscoveryId":      None,
    "DiscoveryPollInt": None,
    "Descr":            _str(row.get("descr")),
    "Vendor":           _str(row.get("vendor")),
    "Model":            _str(row.get("model")),
    "SwVersion":        _str(row.get("swversion")),
    "Sitename":         None,
    "Province":         None,
    "PollStatus":       None,
    "Latitude":         None,
    "Longitude":        None,
    "OltType":          None,
    "Engine":           "nokia-altiplano",
    "Save":             True,
    "Interfaces":       interfaces,
    "Data":             { "Boards": boards},
  }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(output_dir: Path) -> list[dict]:
  """
  Read device.jsonl, intf.jsonl, ponport.jsonl, board.jsonl from output_dir.
  Assemble into Device structs with nested Interfaces and Boards.
  Save as devices.json and return the list.
  """
  device_rows  = _load_jsonl(output_dir / "device.jsonl")
  intf_rows    = _load_jsonl(output_dir / "intf.jsonl")
  ponport_rows = _load_jsonl(output_dir / "ponport.jsonl")
  board_rows   = _load_jsonl(output_dir / "board.jsonl")

  # Group interfaces, ponports, and boards by device_name
  intf_by_device: dict[str, list[dict]] = {}
  for row in intf_rows:
    intf_by_device.setdefault(row.get("device_name", ""), []).append(_map_intf(row))

  ponport_by_device: dict[str, list[dict]] = {}
  for row in ponport_rows:
    ponport_by_device.setdefault(row.get("device_name", ""), []).append(_map_ponport(row))

  board_by_device: dict[str, list[dict]] = {}
  for row in board_rows:
    board_by_device.setdefault(row.get("device_name", ""), []).append(_map_board(row))

  devices = []
  for row in device_rows:
    name = row.get("name", "")
    boards = board_by_device.get(name, [])
    interfaces = intf_by_device.get(name, []) + ponport_by_device.get(name, [])
    devices.append(_map_device(row, interfaces, boards))

  out_path = output_dir / "devices.json"
  out_path.write_text(json.dumps(devices, indent=2, ensure_ascii=False), encoding="utf-8")
  log.info("  saved: devices.json (%d devices, %d interfaces)",
           len(devices), sum(len(d["Interfaces"]) for d in devices))
  return devices


if __name__ == "__main__":
  import argparse
  p = argparse.ArgumentParser(description="Map discovery JSONL output to Device struct format")
  p.add_argument("--output-dir", default="output", help="Directory containing device/intf/ponport/board JSONL files")
  args = p.parse_args()

  run(Path(args.output_dir))
