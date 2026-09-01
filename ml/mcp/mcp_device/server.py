"""MCP server entrypoint: exposes pmsonline.device (FTTx scope) to LLM clients.

Read-only. Runs over stdio (Claude Code / Claude Desktop). See ../README.md
for setup and ../DESIGN.md for the design rationale behind this tool surface.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import resources, tools
from .config import load_settings
from .db import Database

settings = load_settings()
db = Database(settings)

mcp = MCPServer("pmsonline-device")


# --- Resources: low-cardinality reference data, ground the model in real values ---


@mcp.resource("device://vendors")
def device_vendors() -> list[dict]:
    """Distinct device vendor values with counts (all networks)."""
    return resources.vendor_counts(db)


@mcp.resource("device://regions")
def device_regions() -> list[dict]:
    """Distinct device region values with counts (all networks)."""
    return resources.region_counts(db)


@mcp.resource("device://olttypes")
def device_olttypes() -> list[dict]:
    """Distinct device olttype values with counts (all networks)."""
    return resources.olttype_counts(db)


@mcp.resource("device://networks")
def device_networks() -> list[dict]:
    """Distinct device network values with counts, e.g. FTTx, IPRAN, BMA."""
    return resources.network_counts(db)


# --- Tools ---


@mcp.tool()
def device_search(
    query: str | None = None,
    vendor: str | None = None,
    region: str | None = None,
    province: str | None = None,
    olttype: str | None = None,
    network: str = "FTTx",
    pollstatus: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Search network devices (L2/L3, OLT, B-RAS) with filters.

    Defaults to network='FTTx' (this server's primary scope). Pass
    network='all' to search across every network (FTTx, IPRAN, BMA, ...).
    Check the device://vendors, device://regions, device://olttypes,
    device://networks resources for valid filter values before guessing.

    query does a substring match against name, ip, sitename, descr, and dn.
    pollstatus is one of "up", "down", or omitted for either.

    Returns a bounded page of summary rows (not all columns) plus
    total_matched/truncated so you know if there's more beyond this page.
    Use device_get for full detail on one specific device.
    """
    return tools.device_search(
        db,
        settings,
        query=query,
        vendor=vendor,
        region=region,
        province=province,
        olttype=olttype,
        network=network,
        pollstatus=pollstatus,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def device_get(
    id: int | None = None,
    ip: str | None = None,
    name: str | None = None,
) -> dict:
    """Get the full detail row (all columns) for exactly one device.

    Provide exactly one of id, ip, or name. If ip/name matches more than one
    device, returns {found: false, ambiguous: true, candidates: [...]}
    instead of guessing which one you meant.
    """
    return tools.device_get(db, id=id, ip=ip, name=name)


@mcp.tool()
def device_stats(
    group_by: list[str],
    network: str = "FTTx",
    vendor: str | None = None,
    region: str | None = None,
    province: str | None = None,
    olttype: str | None = None,
    pollstatus: str | None = None,
    top_n: int = 20,
) -> dict:
    """Aggregate device counts grouped by 1-3 dimensions, ranked by count.

    group_by elements must be from: vendor, model, region, province, olttype,
    network, sys_pollstatus, sitename. Some of these are high-cardinality
    (e.g. sitename has 9,000+ distinct values) so results are always ordered
    by device_count descending and capped at top_n (default 20, max 100) —
    group_count_total tells you how many groups actually matched, and
    truncated tells you whether you're seeing all of them or just the top
    slice.

    Defaults to network='FTTx'; pass network='all' to widen. Use this instead
    of device_search + manual counting whenever the question is "how many".
    """
    return tools.device_stats(
        db,
        settings,
        group_by=group_by,
        network=network,
        vendor=vendor,
        region=region,
        province=province,
        olttype=olttype,
        pollstatus=pollstatus,
        top_n=top_n,
    )


@mcp.tool()
def device_uplinks(
    id: int | None = None,
    ip: str | None = None,
    name: str | None = None,
) -> dict:
    """Get homing/uplink/ring topology fields for exactly one device.

    Provide exactly one of id, ip, or name. Same not-found/ambiguous shape
    as device_get. Covers the a/b/c-homing site+id columns, uplink_ip/model/
    site 1 and 2, ringid, ringtopo, and topology — all sourced directly from
    the device row (no join to the separate topo table yet).
    """
    return tools.device_uplinks(db, id=id, ip=ip, name=name)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
