"""MCP server exposing the shared tool registry (+ a schema resource, a device card resource, and two prompts).

Mounted by app.main at /mcp (Streamable HTTP, bearer-token protected).
"""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from app.queries import devices, interfaces
from app.queries.schema_doc import SCHEMA_DOC
from app.tools.registry import MCP_TOOLS, mcp_function

INSTRUCTIONS = (
  "Read-only access to the PMS Online network inventory (devices, uptime, interfaces, interface history). "
  "Resolve a device with search_devices or get_device first, then use its numeric device_id with the other tools. "
  "Resolve a subscriber's access id (circuit number) with find_by_accessid. "
  "All results are row-limited; narrow filters when `truncated` is true. Times are Asia/Bangkok (UTC+07:00)."
)

mcp = MCPServer(name="pms-online", title="PMS Online (read-only)", instructions=INSTRUCTIONS, version="0.1.0")

for _t in MCP_TOOLS:
  mcp.add_tool(
    mcp_function(_t),
    name=_t.name,
    description=_t.description,
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=False,
  )


@mcp.resource("pms://schema", name="schema", description="Tables, columns and allowed values", mime_type="text/markdown")
def schema_resource() -> str:
  return SCHEMA_DOC


@mcp.resource("pms://device/{device_id}", name="device-card", description="Markdown summary of one device", mime_type="text/markdown")
async def device_card(device_id: str) -> str:
  d = await devices.get_device(int(device_id))
  if d is None:
    return f"Device {device_id} not found."
  s = await interfaces.interface_summary(d.id)
  u = d.uptime
  lines = [
    f"# {d.name} ({d.ip})",
    f"- id: {d.id}; vendor/model: {d.vendor} {d.model}; sw: {d.swversion or '-'}",
    f"- network/topology: {d.network} / {d.topology}; region/province/site: {d.region} / {d.province} / {d.sitename}",
    f"- poll status: {d.pollstatus}; first seen {d.first}; last seen {d.lastseen}",
    f"- uptime: {u.uptime_text if u else 'n/a'}; last reboot: {u.last_reboot_at if u else 'n/a'}; "
    f"last ping ok: {u.last_ping_success_at if u else 'n/a'}",
    f"- interfaces: {s.total} total; oper {s.by_oper}; with LLDP neighbor {s.with_neighbor}",
  ]
  return "\n".join(lines)


@mcp.prompt(name="investigate_device", description="Investigate the health of one device")
def investigate_device(device: str) -> str:
  return (
    f"Investigate device '{device}'. Resolve it with get_device (by name or IP), then call interface_summary, "
    "list_interface_changes (since_hours=168) and find_neighbors. Summarize identity, uptime/reboots, "
    "interfaces that are down or flapping, and anything unusual. Cite device ids and interface names."
  )


@mcp.prompt(name="region_health", description="Health overview for one region")
def region_health(region: str) -> str:
  return (
    f"Give a health overview of region '{region}'. Use count_devices (region filter, group_by topology), "
    "list_recent_reboots (since_hours=24), list_unreachable_devices (not_seen_for_hours=24) and "
    "top_flapping_interfaces (since_hours=168), all filtered to that region. Summarize with counts and the worst offenders."
  )
