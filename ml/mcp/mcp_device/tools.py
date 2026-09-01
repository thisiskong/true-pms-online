"""Device inventory tool implementations.

Every query here is a fixed, parameterized SQL statement — filter *values*
are always bound params (%s), never string-interpolated. The only dynamic
SQL is column/group-by *names*, and those are always checked against a
hardcoded allowlist before being spliced in, so no user-controlled string
ever reaches the query text.
"""

from __future__ import annotations

from typing import Any, Iterable

from .config import Settings
from .db import Database

SEARCH_COLUMNS = (
    "id, name, ip, vendor, model, olttype, sitename, region, province, "
    "network, sys_pollstatus, lastseen"
)

UPLINK_COLUMNS = (
    "id, name, ip, network, "
    "a_homing_id, a_homing_site, b_homing_id, b_homing_site, "
    "c_homing_id, c_homing_site, "
    "uplink_ip1, uplink_model1, uplink_site1, "
    "uplink_ip2, uplink_model2, uplink_site2, "
    "ringid, ringtopo, topology"
)

STATS_ALLOWED_GROUP_COLS = {
    "vendor",
    "model",
    "region",
    "province",
    "olttype",
    "network",
    "sys_pollstatus",
    "sitename",
}

# Devices found by ip/name are expected to be unique; if a lookup matches more
# than this, something is off with the identifier, but we still cap the
# candidate list returned to the model rather than fetching everything.
MAX_AMBIGUOUS_CANDIDATES = 10


def _base_filters(
    *,
    network: str | None,
    vendor: str | None = None,
    region: str | None = None,
    province: str | None = None,
    olttype: str | None = None,
    pollstatus: str | None = None,
) -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []

    if network and network.strip().lower() != "all":
        where.append("network = %s")
        params.append(network)
    if vendor:
        where.append("vendor = %s")
        params.append(vendor)
    if region:
        where.append("region = %s")
        params.append(region)
    if province:
        where.append("province = %s")
        params.append(province)
    if olttype:
        where.append("olttype = %s")
        params.append(olttype)
    if pollstatus in ("up", "down"):
        where.append("sys_pollstatus = %s")
        params.append(1 if pollstatus == "up" else 0)

    return where, params


def device_search(
    db: Database,
    settings: Settings,
    *,
    query: str | None = None,
    vendor: str | None = None,
    region: str | None = None,
    province: str | None = None,
    olttype: str | None = None,
    network: str | None = None,
    pollstatus: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    network = network if network is not None else settings.default_network
    limit = max(1, min(limit or settings.default_limit, settings.max_limit))
    offset = max(0, offset or 0)

    where, params = _base_filters(
        network=network,
        vendor=vendor,
        region=region,
        province=province,
        olttype=olttype,
        pollstatus=pollstatus,
    )

    if query:
        where.append(
            "(name ILIKE %s OR ip ILIKE %s OR sitename ILIKE %s "
            "OR descr ILIKE %s OR dn ILIKE %s)"
        )
        like = f"%{query}%"
        params.extend([like, like, like, like, like])

    where_sql = " AND ".join(where) if where else "TRUE"

    with db.cursor() as cur:
        cur.execute(f"SELECT count(*) AS n FROM device WHERE {where_sql}", params)
        total = cur.fetchone()["n"]

        cur.execute(
            f"""
            SELECT {SEARCH_COLUMNS}
            FROM device
            WHERE {where_sql}
            ORDER BY id
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        )
        rows = list(cur.fetchall())

    return {
        "rows": rows,
        "total_matched": total,
        "returned": len(rows),
        "truncated": offset + len(rows) < total,
        "filters_applied": {
            "query": query,
            "vendor": vendor,
            "region": region,
            "province": province,
            "olttype": olttype,
            "network": network,
            "pollstatus": pollstatus,
            "limit": limit,
            "offset": offset,
        },
    }


def _one_device_where(
    *, id: int | None, ip: str | None, name: str | None
) -> tuple[str, list[Any]]:
    provided = [v for v in (id, ip, name) if v is not None]
    if len(provided) != 1:
        raise ValueError("Provide exactly one of id, ip, or name")

    if id is not None:
        return "id = %s", [id]
    if ip is not None:
        return "ip = %s", [ip]
    return "name = %s", [name]


def device_get(
    db: Database, *, id: int | None = None, ip: str | None = None, name: str | None = None
) -> dict:
    where_sql, params = _one_device_where(id=id, ip=ip, name=name)

    with db.cursor() as cur:
        cur.execute(
            f"SELECT * FROM device WHERE {where_sql} LIMIT {MAX_AMBIGUOUS_CANDIDATES + 1}",
            params,
        )
        rows = list(cur.fetchall())

    return _resolve_single(rows)


def device_uplinks(
    db: Database, *, id: int | None = None, ip: str | None = None, name: str | None = None
) -> dict:
    where_sql, params = _one_device_where(id=id, ip=ip, name=name)

    with db.cursor() as cur:
        cur.execute(
            f"SELECT {UPLINK_COLUMNS} FROM device WHERE {where_sql} "
            f"LIMIT {MAX_AMBIGUOUS_CANDIDATES + 1}",
            params,
        )
        rows = list(cur.fetchall())

    return _resolve_single(rows)


def _resolve_single(rows: list[dict]) -> dict:
    if not rows:
        return {"found": False}
    if len(rows) > 1:
        return {
            "found": False,
            "ambiguous": True,
            "candidates": [
                {"id": r["id"], "name": r["name"], "ip": r["ip"], "network": r["network"]}
                for r in rows
            ],
        }
    return {"found": True, "device": rows[0]}


def device_stats(
    db: Database,
    settings: Settings,
    *,
    group_by: Iterable[str],
    network: str | None = None,
    vendor: str | None = None,
    region: str | None = None,
    province: str | None = None,
    olttype: str | None = None,
    pollstatus: str | None = None,
    top_n: int | None = None,
) -> dict:
    group_by = list(group_by)
    if not group_by:
        raise ValueError("group_by is required (1-3 columns)")
    if len(group_by) > 3:
        raise ValueError("group_by supports at most 3 columns")

    bad = sorted(set(group_by) - STATS_ALLOWED_GROUP_COLS)
    if bad:
        raise ValueError(
            f"Unsupported group_by column(s): {bad}. "
            f"Allowed: {sorted(STATS_ALLOWED_GROUP_COLS)}"
        )

    network = network if network is not None else settings.default_network
    top_n = max(1, min(top_n or settings.stats_default_top_n, settings.stats_max_top_n))

    where, params = _base_filters(
        network=network,
        vendor=vendor,
        region=region,
        province=province,
        olttype=olttype,
        pollstatus=pollstatus,
    )
    where_sql = " AND ".join(where) if where else "TRUE"
    cols_sql = ", ".join(group_by)  # safe: every element checked against the allowlist above

    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*) AS n FROM (
                SELECT 1 FROM device WHERE {where_sql} GROUP BY {cols_sql}
            ) AS groups
            """,
            params,
        )
        group_count_total = cur.fetchone()["n"]

        cur.execute(
            f"""
            SELECT {cols_sql}, count(*) AS device_count
            FROM device
            WHERE {where_sql}
            GROUP BY {cols_sql}
            ORDER BY device_count DESC
            LIMIT %s
            """,
            [*params, top_n],
        )
        rows = list(cur.fetchall())

    return {
        "rows": rows,
        "group_count_total": group_count_total,
        "truncated": group_count_total > len(rows),
    }
