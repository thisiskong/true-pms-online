"""Response models shared by the REST API, chat tools and MCP tools."""
from datetime import datetime, timedelta, timezone
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

# DB timestamps are `timestamp without time zone` written in Asia/Bangkok local time.
BKK = timezone(timedelta(hours=7), "Asia/Bangkok")

POLL_STATUS = {0: "Disable", 1: "Enable"}

T = TypeVar("T")


def bkk(dt: datetime | None) -> datetime | None:
  if dt is None:
    return None
  return dt.replace(tzinfo=BKK) if dt.tzinfo is None else dt


def now_bkk_naive() -> datetime:
  """Current Bangkok wall-clock time, naive, for comparing with DB timestamps."""
  return datetime.now(BKK).replace(tzinfo=None)


def poll_status(usr: int | None, sys: int | None) -> str | None:
  v = usr if usr is not None else sys
  return POLL_STATUS.get(v) if v is not None else None


def human_duration(td: timedelta | None) -> str | None:
  if td is None:
    return None
  secs = int(td.total_seconds())
  if secs < 0:
    return None
  days, rem = divmod(secs, 86400)
  hours, rem = divmod(rem, 3600)
  minutes = rem // 60
  if days:
    return f"{days}d {hours}h"
  if hours:
    return f"{hours}h {minutes}m"
  return f"{minutes}m"


def human_speed(bps: int | None) -> str | None:
  if bps is None:
    return None
  if bps <= 0:
    return "0"
  units = ["bps", "Kbps", "Mbps", "Gbps", "Tbps"]
  v = float(bps)
  i = 0
  while v >= 1000 and i < len(units) - 1:
    v /= 1000
    i += 1
  return f"{v:g} {units[i]}" if v == int(v) else f"{v:.2f} {units[i]}"


class Page(BaseModel, Generic[T]):
  items: list[T]
  page: int
  size: int
  total: int


class DeviceRow(BaseModel):
  id: int
  name: str | None
  ip: str | None
  vendor: str | None
  model: str | None
  network: str | None
  topology: str | None
  region: str | None
  province: str | None
  sitename: str | None
  pollstatus: str | None
  first: datetime | None
  lastseen: datetime | None


class Uptime(BaseModel):
  ip: str
  polled_at: datetime | None
  poll_method: str | None
  uptime_seconds: int | None
  uptime_text: str | None
  last_reboot_at: datetime | None
  last_ping_success_at: datetime | None
  last_ping_rtt_ms: float | None


class Device(BaseModel):
  id: int
  name: str | None
  ip: str | None
  chassisid: str | None
  descr: str | None
  vendor: str | None
  model: str | None
  swversion: str | None
  olttype: str | None
  network: str | None
  topology: str | None
  region: str | None
  province: str | None
  sitename: str | None
  latitude: float | None
  longitude: float | None
  rn: str | None
  pn: str | None
  dn: str | None
  ringid: str | None
  ringtopo: str | None
  hop: str | None
  uplink_ip1: str | None
  uplink_site1: str | None
  uplink_model1: str | None
  uplink_ip2: str | None
  uplink_site2: str | None
  uplink_model2: str | None
  a_homing_id: str | None
  a_homing_site: str | None
  b_homing_id: str | None
  b_homing_site: str | None
  c_homing_id: str | None
  c_homing_site: str | None
  agent: str | None
  pollint: int | None
  pollstatus: str | None
  first: datetime | None
  lastseen: datetime | None
  last_modify_at: datetime | None
  last_modify_by: str | None
  uptime: Uptime | None = None


class Interface(BaseModel):
  id: str
  device_id: int | None
  ifindex: str | None
  ifname: str | None
  ifalias: str | None
  ifdescr: str | None
  iftype: str | None
  ifspeed: int | None
  speed_text: str | None
  ifadmin: str | None
  ifoper: str | None
  ifphyaddr: str | None
  dstname: str | None
  dstport: str | None
  dstsite: str | None
  dsttype: str | None
  mediatype: str | None
  vendorpn: str | None
  moduleclass: str | None
  pollstatus: str | None
  first: datetime | None
  lastseen: datetime | None


class PonPort(BaseModel):
  id: str
  device_id: int | None
  ponport: str | None
  ifindex: str | None
  ifname: str | None
  ifalias: str | None
  ifdescr: str | None
  iftype: str | None
  ifspeed: int | None
  speed_text: str | None
  ifadmin: str | None
  ifoper: str | None
  ifconn: int | None
  l1sp: str | None
  l1_dl_max_bw: int | None
  l1_ul_max_bw: int | None
  dl_bw_remaining: str | None
  ul_bw_remaining: str | None
  moduleclass: str | None
  vendorpn: str | None
  # Normalised from moduleclass, else learned from vendorpn (app/queries/optics.py).
  optic_class: str | None = None         # B+, C+, C++, D, "absent" (no optic), or None (unknown)
  optic_tech: str | None = None          # GPON or GPON+XGS-PON
  optic_class_source: str | None = None  # "moduleclass" or "vendorpn"
  pollstatus: str | None
  first: datetime | None
  lastseen: datetime | None
  onu_count: int = 0
  onu_capacity: int | None = None  # port split ratio from odn_onu (available ONU slots)


class Onu(BaseModel):
  """One subscriber ONU on a PON port (odn_onu)."""
  ontid: str | None
  accessid: str | None
  devicesn: str | None
  l1name: str | None
  l2name: str | None
  l1ratio: int | None
  l2ratio: int | None
  splitratio: int | None
  l1len: float | None
  l2len: float | None
  dropwire: float | None
  ranging: float | None
  ranging_exclude: bool | None
  vendor: str | None
  model: str | None
  moduleclass: str | None
  l2date: datetime | None
  hsidate: datetime | None


class InterfaceSummary(BaseModel):
  device_id: int
  total: int
  by_oper: dict[str, int]
  by_admin: dict[str, int]
  by_speed: dict[str, int]
  by_type: dict[str, int]
  with_neighbor: int


class IntfChange(BaseModel):
  id: str
  rev: int
  device_id: int | None
  device_name: str | None = None
  device_ip: str | None = None
  ifindex: str | None
  ifname: str | None
  ifalias: str | None
  ifoper: str | None
  ifspeed: int | None
  speed_text: str | None
  first: datetime | None
  lastseen: datetime | None


class Neighbor(BaseModel):
  ifname: str | None
  ifalias: str | None
  ifoper: str | None
  dstname: str | None
  dstport: str | None
  dstsite: str | None
  neighbor_device_id: int | None
  neighbor_ip: str | None


def rec(r: Any) -> dict[str, Any]:
  """asyncpg Record -> dict with Bangkok-aware datetimes."""
  d = dict(r)
  for k, v in d.items():
    if isinstance(v, datetime):
      d[k] = bkk(v)
  return d
