"""Single tool registry shared by the Claude chat orchestrator and the MCP server.

Each tool = a strict Pydantic input model + an async handler returning JSON-able data.
Outputs are bounded (row limits + a byte cap) so a model can never pull bulk data.
"""
import inspect
import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.queries import access, changes, devices, interfaces, intf_fleet, stats, uptime
from app.queries.devices import DeviceFilters
from app.queries.models import now_bkk_naive
from app.queries.schema_doc import SCHEMA_DOC
from app.tools import fiber_tools as ft

MAX_RESULT_BYTES = 20_000


class ToolInputError(Exception):
  """Anticipated, model-correctable error (bad id, ambiguous name, ...)."""


class _In(BaseModel):
  model_config = ConfigDict(extra="forbid")


class _Filters(_In):
  q: str | None = Field(None, max_length=100, description="Substring of device name or site name, or an IP prefix")
  vendor: str | None = Field(None, max_length=50, description="Exact vendor, e.g. Huawei, ZTE, Nokia")
  model: str | None = Field(None, max_length=80, description="Exact model, e.g. MA5800-X2")
  network: str | None = Field(None, max_length=50, description="Exact network, e.g. IPRAN, FTTx, BMA")
  topology: str | None = Field(None, max_length=50, description="Exact topology, e.g. OLT, CPE, AGN, DN, AN, PN")
  region: str | None = Field(None, max_length=50, description="Exact region, e.g. Central, West")
  province: str | None = Field(None, max_length=80, description="Exact province")
  sitename: str | None = Field(None, max_length=80, description="Exact site name")
  pollstatus: Literal["Enable", "Disable"] | None = Field(None, description="Polling status")

  def filters(self) -> DeviceFilters:
    return DeviceFilters(**self.model_dump(include=set(_Filters.model_fields)))


# ---------- inputs ----------

class SearchDevicesIn(_Filters):
  limit: int = Field(20, ge=1, le=50, description="Max rows (1-50)")


class GetDeviceIn(_In):
  device_id: int | None = Field(None, description="Device id (preferred)")
  name: str | None = Field(None, max_length=120, description="Exact device name (sysName)")
  ip: str | None = Field(None, max_length=45, description="Exact management IP")


class CountDevicesIn(_Filters):
  group_by: Literal["vendor", "model", "network", "topology", "region", "province", "pollstatus"] | None = Field(
    None, description="Optional dimension to group counts by (top 50 groups)")


class FilterValuesIn(_In):
  field: Literal["vendor", "model", "network", "topology", "region", "province"] = Field(
    ..., description="Device column to list distinct values for")


class DeviceIdIn(_In):
  device_id: int = Field(..., description="Device id (from search_devices / get_device)")


class RebootsIn(_Filters):
  since_hours: int = Field(24, ge=1, le=720, description="Look back this many hours (max 720 = 30 days)")
  limit: int = Field(50, ge=1, le=100, description="Max rows (1-100)")


class UnreachableIn(_Filters):
  not_seen_for_hours: int = Field(24, ge=1, le=720, description="No successful ping for at least this many hours")
  limit: int = Field(50, ge=1, le=100, description="Max rows (1-100)")


class ListInterfacesIn(_In):
  device_id: int = Field(..., description="Device id")
  oper: Literal["up", "down", "lowerLayerDown", "dormant", "notPresent"] | None = Field(None, description="Filter by oper status")
  q: str | None = Field(None, max_length=100, description="Substring of ifname, ifalias or LLDP neighbor name")
  has_neighbor: bool | None = Field(None, description="true = only interfaces with an LLDP neighbor")
  limit: int = Field(50, ge=1, le=100, description="Max rows (1-100)")


class FleetIntfIn(_Filters):
  """Device filters (inherited: q, vendor, topology, region, ...) plus interface filters, across ALL devices."""
  oper: Literal["up", "down", "lowerLayerDown", "dormant", "notPresent"] | None = Field(None, description="Interface oper status")
  admin: Literal["up", "down", "testing"] | None = Field(None, description="Interface admin status")
  dsttype: str | None = Field(None, max_length=50, description="Exact type of what the port connects to (from its description), e.g. OLT, CPE, Corporate, NodeB, WiFi, PN, DN")
  moduleclass: str | None = Field(None, max_length=50, description="Exact optic module class, e.g. 10GBASE-LR")
  min_speed_mbps: int | None = Field(None, ge=0, le=10_000_000, description="Only interfaces at least this fast, in Mbit/s (10000 = 10G)")
  max_speed_mbps: int | None = Field(None, ge=0, le=10_000_000, description="Only interfaces at most this fast, in Mbit/s")
  text: str | None = Field(None, max_length=100, description="Substring of ifname, description (ifalias), LLDP neighbor name, dst site or dst port")
  has_neighbor: bool | None = Field(None, description="true = only interfaces with an LLDP neighbor; false = only without")

  def where(self):
    return intf_fleet._fleet_where(self.filters(), self.oper, self.admin, self.dsttype, self.moduleclass,
                                   self.min_speed_mbps, self.max_speed_mbps, self.text, self.has_neighbor)


class SearchInterfacesIn(FleetIntfIn):
  limit: int = Field(50, ge=1, le=100, description="Max rows (1-100)")


class CountInterfacesIn(FleetIntfIn):
  group_by: Literal["oper", "admin", "speed", "dsttype", "moduleclass", "iftype", "vendor", "model", "topology", "region", "province", "device"] | None = Field(
    None, description="Optional dimension to group counts by; 'device' gives the devices with the most matching interfaces")
  limit: int = Field(50, ge=1, le=50, description="Max groups (1-50)")

  def model_post_init(self, _: Any) -> None:
    if self.group_by == "device" and self.limit == 50:
      self.limit = 20  # long device leaderboards are rarely useful and cost tokens


class GetInterfaceIn(_In):
  interface_id: str | None = Field(None, max_length=40, description='Interface id "<device_id>.<ifindex>"')
  device_id: int | None = Field(None, description="Device id (use with ifname)")
  ifname: str | None = Field(None, max_length=120, description="Exact interface name, e.g. GigabitEthernet0/2/1")


class ChangesIn(_In):
  device_id: int | None = Field(None, description="Limit to one device")
  interface_id: str | None = Field(None, max_length=40, description='Limit to one interface "<device_id>.<ifindex>"')
  since_hours: int | None = Field(None, ge=1, le=720, description="Only changes that started within this many hours (required when no device/interface given)")
  limit: int = Field(50, ge=1, le=100, description="Max rows (1-100)")


class FlappingIn(_Filters):
  since_hours: int = Field(168, ge=1, le=720, description="Look back this many hours (default 7 days, max 30 days)")
  limit: int = Field(20, ge=1, le=50, description="Max rows (1-50)")


class NoIn(_In):
  pass


class AccessIdIn(_In):
  accessid: str = Field(..., min_length=4, max_length=60, description="Access id / circuit number, e.g. 9605163336")
  tickets: int = Field(10, ge=0, le=20, description="Max trouble tickets to return, newest first (0-20)")


class ChartSeries(_In):
  name: str = Field(..., max_length=60, description="Series name (legend label)")
  values: list[float] = Field(..., min_length=1, max_length=50, description="One number per label, in label order")


class ShowChartIn(_In):
  type: Literal["pie", "bar", "hbar", "line"] = Field(..., description="pie = parts of a whole (one series); bar/hbar = compare categories; line = trend over time")
  title: str = Field("", max_length=100, description="Short chart title")
  labels: list[str] = Field(..., min_length=1, max_length=50, description="Category or time labels (x axis, or pie slices)")
  series: list[ChartSeries] = Field(..., min_length=1, max_length=5, description="Data series; pie uses exactly one")
  unit: str | None = Field(None, max_length=20, description="Optional value unit, e.g. devices, %, ms")


# ---------- handlers ----------

def _since(hours: int):
  return now_bkk_naive() - timedelta(hours=hours)


def _dump(v: Any) -> Any:
  if isinstance(v, BaseModel):
    return v.model_dump(mode="json")
  if isinstance(v, list):
    return [_dump(x) for x in v]
  if isinstance(v, dict):
    return {k: _dump(x) for k, x in v.items()}
  return v


async def search_devices(a: SearchDevicesIn) -> dict:
  page = await devices.list_devices(a.filters(), 1, a.limit, "name", "asc")
  return {"items": page.items, "total": page.total, "truncated": page.total > len(page.items)}


async def get_device(a: GetDeviceIn) -> dict:
  if a.device_id is not None:
    d = await devices.get_device(a.device_id)
    if d is None:
      raise ToolInputError(f"device_id {a.device_id} not found")
    return {"device": d}
  if not (a.name or a.ip):
    raise ToolInputError("give one of device_id, name or ip")
  rows = await devices.find_devices_by_key(name=a.name, ip=a.ip)
  if not rows and a.name:
    near = await devices.list_devices(DeviceFilters(q=a.name), 1, 10)
    raise ToolInputError(
      f"no device named exactly '{a.name}'. Similar: "
      + json.dumps([{"id": r.id, "name": r.name, "ip": r.ip} for r in near.items])
    )
  if not rows:
    raise ToolInputError(f"no device with ip {a.ip}")
  if len(rows) > 1:
    return {"ambiguous": True, "candidates": rows, "hint": "call get_device again with device_id"}
  return {"device": await devices.get_device(rows[0].id)}


async def count_devices(a: CountDevicesIn) -> dict:
  return await devices.count_devices(a.filters(), a.group_by)


async def list_filter_values(a: FilterValuesIn) -> dict:
  vals = await devices.facet_values(a.field)
  return {"field": a.field, "values": vals[:200], "truncated": len(vals) > 200}


async def get_device_uptime(a: DeviceIdIn) -> dict:
  return {"device_id": a.device_id, "uptime": await uptime.get_uptime(a.device_id)}


async def list_recent_reboots(a: RebootsIn) -> dict:
  return await uptime.list_recent_reboots(_since(a.since_hours), a.filters(), a.limit)


async def list_unreachable_devices(a: UnreachableIn) -> dict:
  return await uptime.list_unreachable(a.not_seen_for_hours, a.filters(), a.limit)


async def interface_summary(a: DeviceIdIn) -> dict:
  return {"summary": await interfaces.interface_summary(a.device_id)}


async def list_interfaces(a: ListInterfacesIn) -> dict:
  page = await interfaces.list_interfaces(a.device_id, 1, a.limit, oper=a.oper, q=a.q, has_neighbor=a.has_neighbor)
  return {"items": page.items, "total": page.total, "truncated": page.total > len(page.items)}


async def search_interfaces(a: SearchInterfacesIn) -> dict:
  return await intf_fleet.search_fleet(a.where(), a.limit)


async def count_interfaces(a: CountInterfacesIn) -> dict:
  return await intf_fleet.count_fleet(a.where(), a.group_by, a.limit)


async def get_interface(a: GetInterfaceIn) -> dict:
  if not (a.interface_id or (a.device_id is not None and a.ifname)):
    raise ToolInputError("give interface_id, or device_id + ifname")
  i = await interfaces.get_interface(a.interface_id, a.device_id, a.ifname)
  if i is None:
    raise ToolInputError("interface not found")
  return {"interface": i}


async def find_neighbors(a: DeviceIdIn) -> dict:
  return await interfaces.find_neighbors(a.device_id)


async def list_interface_changes(a: ChangesIn) -> dict:
  if a.device_id is None and not a.interface_id and a.since_hours is None:
    raise ToolInputError("give device_id, interface_id, or since_hours")
  since = _since(a.since_hours) if a.since_hours else None
  return await changes.list_changes(a.device_id, a.interface_id, since, a.limit)


async def top_flapping_interfaces(a: FlappingIn) -> dict:
  return await changes.top_flapping(_since(a.since_hours), a.filters(), a.limit)


async def fleet_overview(a: NoIn) -> dict:
  return await stats.fleet_overview()


async def describe_schema(a: NoIn) -> dict:
  return {"schema": SCHEMA_DOC}


async def find_by_accessid(a: AccessIdIn) -> dict:
  r = await access.lookup(a.accessid, a.tickets)  # ValueError (bad format) -> ToolInputError
  if r is None:
    raise ToolInputError(f"no ONU has access id {a.accessid.strip()} (odn_onu); check the number")
  return r


async def show_chart(a: ShowChartIn) -> dict:
  n = len(a.labels)
  bad = [x.name for x in a.series if len(x.values) != n]
  if bad:
    raise ToolInputError(f"each series needs exactly {n} values (one per label); wrong length: {bad}")
  if a.type == "pie" and len(a.series) != 1:
    raise ToolInputError("a pie chart takes exactly one series")
  return {"chart": a.model_dump(mode="json")}


# ---------- registry ----------

@dataclass
class ToolDef:
  name: str
  description: str
  input_model: type[_In]
  handler: Callable[[Any], Awaitable[dict]]
  table_columns: list[str] = field(default_factory=list)
  chat_only: bool = False  # UI tools (e.g. show_chart) are not exposed over MCP

  def input_schema(self) -> dict:
    return _clean_schema(self.input_model.model_json_schema())

  def claude_tool(self) -> dict:
    return {
      "name": self.name,
      "description": self.description,
      "input_schema": self.input_schema(),
      "eager_input_streaming": True,
    }

  async def run(self, raw: Any) -> dict:
    """Validate raw input, run, and return a bounded JSON-able result. Raises ToolInputError."""
    if not isinstance(raw, dict):
      raise ToolInputError("tool input must be a JSON object")
    try:
      args = self.input_model.model_validate(raw)
    except ValidationError as e:
      raise ToolInputError(f"invalid input: {e.errors(include_url=False, include_context=False)}") from e
    try:
      out = await self.handler(args)
    except ValueError as e:
      raise ToolInputError(str(e)) from e
    return _bound(_dump(out))


def _clean_schema(s: Any) -> Any:
  if isinstance(s, dict):
    return {k: _clean_schema(v) for k, v in s.items() if k != "title"}
  if isinstance(s, list):
    return [_clean_schema(x) for x in s]
  return s


def _bound(out: dict) -> dict:
  """Trim list results until the serialized output fits MAX_RESULT_BYTES."""
  text = json.dumps(out, default=str)
  if len(text) <= MAX_RESULT_BYTES:
    return out
  key = next((k for k in ("items", "candidates", "values") if isinstance(out.get(k), list)), None)
  if key is None:
    return {"error": "result too large", "preview": text[:MAX_RESULT_BYTES]}
  items = out[key]
  while items and len(json.dumps(out, default=str)) > MAX_RESULT_BYTES:
    items = items[: max(1, len(items) * 3 // 4)] if len(items) > 1 else []
    out = {**out, key: items, "truncated": True, "note": "result trimmed to fit size limit; narrow the query"}
  return out


DEV_COLS = ["id", "name", "ip", "vendor", "model", "topology", "region", "sitename"]

TOOLS: list[ToolDef] = [
  ToolDef("search_devices",
    "Search the device inventory. Filters are exact matches except q (substring of name/site, or IP prefix). "
    "Returns compact rows with device ids; use get_device for details. Use list_filter_values to learn valid filter values.",
    SearchDevicesIn, search_devices, DEV_COLS + ["lastseen"]),
  ToolDef("get_device",
    "Get full details of one device (identity, location, topology hierarchy, uplinks, homing, poll status) plus its "
    "latest uptime/reboot/ping data. Look up by device_id (preferred), exact name, or exact IP. "
    "Returns candidates when a name/IP matches several devices.",
    GetDeviceIn, get_device),
  ToolDef("count_devices",
    "Count devices matching filters, optionally grouped by vendor, model, network, topology, region, province or pollstatus.",
    CountDevicesIn, count_devices, ["value", "count"]),
  ToolDef("list_filter_values",
    "List distinct values (with device counts) of a device column, to pick valid filter values.",
    FilterValuesIn, list_filter_values, ["value", "count"]),
  ToolDef("get_device_uptime",
    "Latest uptime, last reboot time, last successful ping and RTT for one device. null when the device is not polled for uptime.",
    DeviceIdIn, get_device_uptime),
  ToolDef("list_recent_reboots",
    "Devices that rebooted within the last since_hours (max 30 days), newest first. Accepts the same device filters as search_devices.",
    RebootsIn, list_recent_reboots, DEV_COLS + ["uptime.last_reboot_at", "uptime.uptime_text"]),
  ToolDef("list_unreachable_devices",
    "Devices with uptime polling whose last successful ping is older than not_seen_for_hours (or never). Accepts device filters.",
    UnreachableIn, list_unreachable_devices, DEV_COLS + ["uptime.last_ping_success_at"]),
  ToolDef("interface_summary",
    "Interface counts for one device by oper status, admin status, speed bucket and type, plus how many have an LLDP neighbor.",
    DeviceIdIn, interface_summary),
  ToolDef("list_interfaces",
    "List interfaces of one device (ifname, ifalias/description, oper/admin status, speed, LLDP neighbor). "
    "Filter by oper status, substring q, or has_neighbor. For questions spanning many devices use search_interfaces "
    "or count_interfaces instead of calling this per device.",
    ListInterfacesIn, list_interfaces, ["ifname", "ifalias", "ifoper", "ifadmin", "speed_text", "dstname", "dstport"]),
  ToolDef("search_interfaces",
    "Search interfaces across ALL devices at once (no need to loop over devices). Combine device filters "
    "(topology, vendor, model, region, province, q, ...) with interface filters (oper, admin, dsttype, moduleclass, "
    "min/max speed in Mbit/s, text, has_neighbor). Returns matching rows with device name/IP and the total count. "
    "Use count_interfaces instead when the question is 'how many'.",
    SearchInterfacesIn, search_interfaces,
    ["device_name", "device_ip", "ifname", "ifalias", "speed_text", "ifoper", "ifadmin", "dsttype", "dstsite", "dstname", "dstport"]),
  ToolDef("count_interfaces",
    "Count interfaces across ALL devices at once, optionally grouped by oper, admin, speed bucket, dsttype, moduleclass, "
    "iftype, vendor, model, topology, region, province or device (top 50 groups; group_by=device also returns each device's "
    "id, IP, vendor, model, region and province, and how many devices matched in total). Same filters as search_interfaces. "
    "Example: down 10G+ interfaces on OLTs per region = topology=OLT, oper=down, min_speed_mbps=10000, group_by=region.",
    CountInterfacesIn, count_interfaces, ["value", "ip", "vendor", "model", "region", "count"]),
  ToolDef("get_interface",
    'Full record of one interface by interface_id ("<device_id>.<ifindex>") or by device_id + exact ifname.',
    GetInterfaceIn, get_interface),
  ToolDef("find_neighbors",
    "LLDP neighbors of one device: local port, remote system name and port, and the neighbor's device id/IP when it is a known device.",
    DeviceIdIn, find_neighbors, ["ifname", "ifoper", "dstname", "dstport", "neighbor_device_id", "neighbor_ip"]),
  ToolDef("list_interface_changes",
    "Interface state history (oper status / speed changes) from intf_rev, newest first. Each row is a state interval "
    "from `first` to `lastseen`. Give device_id, interface_id, and/or since_hours (required if neither id is given).",
    ChangesIn, list_interface_changes, ["device_name", "ifname", "ifalias", "rev", "ifoper", "speed_text", "first", "lastseen"]),
  ToolDef("top_flapping_interfaces",
    "Interfaces with the most state changes within since_hours (default 7 days, max 30), with device name/IP. Accepts device filters. "
    "changes = oper or speed changes (the first sighting of an interface is not counted); down_changes = changes into a non-up state; "
    "ifoper = current state. The history comes from a once-a-day poll, so changes are at least ~24 h apart: this finds interfaces "
    "that are unstable day to day, not sub-minute flapping.",
    FlappingIn, top_flapping_interfaces,
    ["device_name", "device_ip", "ifname", "ifalias", "changes", "oper_changes", "down_changes", "speed_changes", "ifoper", "last_change"]),
  ToolDef("fleet_overview",
    "Fleet KPIs: device counts by network/topology/vendor/poll status, reboots and unreachable devices in the last 24h/7d, "
    "interface oper-status totals, interface changes in the last 24h. Cached for 5 minutes.",
    NoIn, fleet_overview),
  ToolDef("describe_schema",
    "Describe the available data: tables, column meanings, allowed values, and how they relate. Call this when unsure what a field means.",
    NoIn, describe_schema),
  ToolDef("find_by_accessid",
    "Look up a subscriber by access id (circuit number, usually 10 digits): the ONU (OLT name + device_id, PON port, "
    "ONT id, serial), its ODN path (L1/L2 splitters, split ratios, fiber lengths), its latest fiber score, and its "
    "trouble tickets (newest first; the ticket table is a historical extract, see data_from/data_to). Use the returned "
    "device_id, ponport and ontid with get_onu_fiber_score or the device tools.",
    AccessIdIn, find_by_accessid),
  ToolDef("fiber_overview",
    "Fiber-health KPIs from the daily GPON fiber-score batch (latest run, or a given date): ONUs scored, bad ONUs "
    "(score <= 4), score histogram, where bad ONUs are attributed (drop, l2, l1, device, onu_hw), suspect counts, "
    "model error, and the previous run for deltas.",
    ft.FiberOverviewIn, ft.fiber_overview),
  ToolDef("list_fiber_suspects",
    "Ranked suspect fiber locations for the field team: L2 splitter segments, L1 feeders / PON ports, or whole OLTs "
    "where bad ONUs cluster beyond chance. Default sort is impact (biggest payoff first). Filter by region, province, vendor or q.",
    ft.FiberSuspectsIn, ft.list_fiber_suspects,
    ["device", "l1name", "l2name", "province", "n_onu", "n_bad", "bad_share", "med_peer_delta", "med_excess_loss", "impact"]),
  ToolDef("fiber_device_tree",
    "ODN tree of one OLT from the fiber score: per PON port (L1) and its L2 segments, ONU and bad-ONU counts, min score, "
    "median Rx / excess loss / peer delta, whether each node is on a suspect list, and how its bad ONUs were attributed.",
    ft.FiberTreeIn, ft.fiber_device_tree,
    ["ponport", "l1name", "n_onu", "n_bad", "min_score", "med_rx", "med_excess_loss", "suspect"]),
  ToolDef("list_fiber_onus",
    "ONUs of one OLT with their fiber score, worst first (default: only bad, score <= 4). Filter by PON port, L1 or L2 name.",
    ft.FiberOnusIn, ft.list_fiber_onus,
    ["ponport", "ontid", "l2name", "score", "conf", "rx_med", "expected_rx", "excess_loss", "peer_delta_l2", "attributed_to"]),
  ToolDef("get_onu_fiber_score",
    "Full fiber score of one ONU (OLT + PON port + ONT id): score, confidence, sub-scores with effective weights, caps "
    "that limited the score, measured vs expected Rx, peer deltas, path length/split, flags, likely fault location "
    "(attributed_to), and recent daily Rx/BIP history.",
    ft.OnuScoreIn, ft.get_onu_fiber_score),
  ToolDef("show_chart",
    "Display a chart to the user in the chat (pie, bar, hbar or line). This is the only way to show a chart: "
    "never write SVG, Mermaid, chart code or ASCII charts. Use numbers taken from tool results in this conversation. "
    "For pie charts with many slices, keep the top ~10 and group the rest as 'Other'.",
    ShowChartIn, show_chart, chat_only=True),
]

MCP_TOOLS: list[ToolDef] = [t for t in TOOLS if not t.chat_only]

TOOLS_BY_NAME: dict[str, ToolDef] = {t.name: t for t in TOOLS}


def mcp_function(tool: ToolDef) -> Callable[..., Awaitable[dict]]:
  """Build a keyword-argument function whose signature mirrors the tool's input model (for MCPServer.add_tool)."""
  params = []
  annotations: dict[str, Any] = {}
  for fname, finfo in tool.input_model.model_fields.items():
    # FieldInfo as default keeps description/constraints; a required FieldInfo stays required.
    params.append(inspect.Parameter(fname, inspect.Parameter.KEYWORD_ONLY, default=finfo, annotation=finfo.annotation))
    annotations[fname] = finfo.annotation

  async def fn(**kwargs: Any) -> dict:
    from mcp.server.mcpserver.exceptions import ToolError
    try:
      return await tool.run(kwargs)
    except ToolInputError as e:
      raise ToolError(str(e)) from e

  fn.__name__ = tool.name
  fn.__doc__ = tool.description
  fn.__signature__ = inspect.Signature(params, return_annotation=dict)  # type: ignore[attr-defined]
  annotations["return"] = dict
  fn.__annotations__ = annotations
  return fn
