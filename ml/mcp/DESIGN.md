# MCP Server Design — Device Inventory for FTTx Network

## 1. Problem framing

`pmsonline` is a large operational DB (83 core tables + ~2,250 time-partitioned
tables like `bras_traffic1w_p*`, `radius1d_p*`, etc. — TimescaleDB-style weekly
chunks). The `device` table alone holds **45,740 rows**: L2/L3 switches, OLTs,
B-RAS, spread across vendors (Huawei, ZTE, Nokia, GCOM, Fiberhome, Dasan,
Raisecom, A10, Juniper) and 10 regions.

Two things follow directly from that scale, and they drive every decision below:

1. **An LLM must never see raw SQL / the full catalog.** Handing a model
   `execute_sql(query)` against a DB with ~2,300 tables invites it to `SELECT *`
   a multi-million-row partition, blow its own context window, or wander into
   tables it has no business reading (subscriber/RADIUS PII in `bras_*`,
   `fttx_subscriber`, `cpe_map`). The MCP surface must be a **curated set of
   tools**, each with bounded, predictable output — not a SQL pass-through.
2. **45,740 rows means every "list" tool needs filtering + pagination by
   default**, not as an afterthought. A tool that can return "all devices" with
   no cap will get called that way eventually.

## 2. Principles

- **Least privilege at two layers**: the DB role (`pmsonline_ro`, SELECT-only,
  already provisioned — see [db-create-user.sql](db-create-user.sql)) *and* the
  MCP tool surface (only `device` + a few lookup tables to start, not the
  whole schema).
- **Curated tools, not a query console.** Every tool wraps a fixed,
  parameterized query. Filter values are bound params (`%s`), never
  string-interpolated — SQL-injection-safe even though the role is read-only,
  because injection could still be used to read rows the tool wasn't meant to
  expose (e.g. smuggling a `UNION SELECT` from `fttx_subscriber`).
- **Bounded output, always.** Every list-style tool takes a `limit` the server
  clamps server-side (default 50, hard max 200), and a `columns`/`detail` knob
  so the model isn't handed all 42 columns when it asked "how many Huawei OLTs
  in BMA".
- **Ground the model in real values, don't let it guess.** Vendor names,
  regions, olttypes are low-cardinality and stable — expose them as MCP
  **resources** the model reads once, instead of hoping it free-texts
  `"Huawei "` with a trailing space and gets zero rows.
- **Defense in depth at the DB session level**: every connection sets
  `statement_timeout` and `SET TRANSACTION READ ONLY` explicitly, on top of the
  role already being SELECT-only — belt and suspenders against a runaway query.
- **Extensible namespace.** Tool names are prefixed `device_*` on purpose, so
  Phase 2/3 additions (`intf_*`, `topo_*`, `olt_*`, `bras_*`) don't collide or
  require a redesign.

## 3. What `device` actually looks like (grounds the design)

Queried live against `dv01` (`pmsonline_ro`):

| Dimension | Values |
|---|---|
| Row count | 45,740 (all networks) |
| `network` | IPRAN (25,378), **FTTx (13,172)**, BMA (6,882), SPECIAL (236), BFKT (32), CN (24), CMTS (8), TUC (8) |
| `vendor` | Huawei (20,124), ZTE (11,722), Nokia (5,433), GCOM (2,302), Fiberhome (2,114), Dasan (1,991), Raisecom (1,824), A10 (99), Juniper (12), NULL (119) |
| `model` | 28 distinct values within `network='FTTx'` — low cardinality, safe to group by |
| `olttype` | NULL (32,568 — non-OLT devices), Indoor (8,069), Outdoor (4,754), EDFA (172), VlgDslam, BldDslam, Lab, MSAN, Other, CorpOnly |
| `region` | NULL (21,666), BMA, Central, Upper NEA, East, West, Lower NEA, Upper North, Lower South, Lower North, Upper South |
| `sitename` | **9,074 distinct values** within `network='FTTx'` alone — high cardinality, must not be grouped-by unranked (see `device_stats` below) |
| `sys_pollstatus`/`usr_pollstatus` | mostly `(1, NULL)` — integer flags, not FKs to a lookup table |

**Decision: this MCP's scope is FTTx.** The `device` table spans multiple
networks (IPRAN core devices included), but this server exists to answer
questions about the FTTx access network specifically. Every multi-row tool
therefore defaults its `network` filter to `'FTTx'` — callers can pass
`network="all"` to widen it, but the default keeps IPRAN/BMA/core devices out
of FTTx-scoped answers by construction rather than relying on the model to
remember to filter.

Related tables worth knowing about (not exposed yet, but shape future tools):

- **`intf`** — interfaces, FK'd via `device_id` (+ denormalized `device_name`,
  `device_ip`). This is the natural next tool: "what interfaces does device X
  have".
- **`topo`** — link-level topology as `a_device`/`b_device` pairs with
  `a_deviceid`/`b_deviceid`. Powers a `device_neighbors` tool later.
- **`province_code`** — maps province/district codes ↔ Thai/English names.
  `device` itself doesn't store a raw province code (it stores `province` as
  free text already), so this is lower priority.
- **`tag`** — generic `(objid, objtype) → name` tagging, could enrich device
  listings later.
- `bras_ip_mgmt`, `bras_topo`, `fttx_subscriber`, `cpe_map` — subscriber/BRAS
  data. **Deliberately out of scope for this MCP** unless/until there's a
  specific need — this is where PII and higher blast-radius data lives.

## 4. MCP surface — Phase 1 (device inventory only)

### Resources (static/low-cardinality reference data, read once, cached)

| URI | Contents |
|---|---|
| `device://vendors` | distinct `vendor` values + counts |
| `device://olttypes` | distinct `olttype` values + counts |
| `device://regions` | distinct `region` values + counts |
| `device://networks` | distinct `network` values + counts |
| `device://schema` | the curated column list + description each tool exposes (so the model knows what it *can* ask for without seeing raw `information_schema`) |

These are cheap `GROUP BY` queries, refreshed via a short TTL cache (e.g. 10
min) in the server process — no need to hit Postgres on every resource read.

### Tools

**`device_search`** — the main entry point.
```
Input:
  query: string (optional) — matched against name, ip, sitename, descr, dn (ILIKE, prefix+contains)
  vendor: string (optional, enum-checked against device://vendors)
  region: string (optional)
  province: string (optional)
  olttype: string (optional)
  network: string (default "FTTx"; pass "all" to widen)
  pollstatus: "up" | "down" | "any" (optional; maps to sys_pollstatus)
  limit: int (default 50, max 200)
  offset: int (default 0)
Output:
  rows: [{id, name, ip, vendor, model, olttype, sitename, region, province,
          network, sys_pollstatus, lastseen}]   -- summary projection, NOT all 42 cols
  total_matched: int   -- so the model knows if it's seeing a partial slice
  truncated: bool
```

**`device_get`** — full detail for one device.
```
Input: exactly one of { id: int } | { ip: string } | { name: string }
Output: full row (all 42 columns), or {found: false}, or
        {found: false, ambiguous: true, candidates: [...]} if ip/name matches
        more than one row — never silently picks one
```

**`device_stats`** — aggregate counts without ever materializing row lists.
Answers "how many OLTs per region" without the model having to page through
hundreds of rows and count them itself.

Cardinality varies wildly across the allowed dimensions — `model` is 28
distinct values (FTTx-scoped), `sitename` is 9,074. `vendor + model +
sitename` alone is 10,608 groups, which would defeat the point of a "stats"
tool if returned unranked. So instead of a flat row cap, `device_stats`
always ranks by count and returns a bounded top-N slice plus the true group
count, the same truncation pattern `device_search` uses for rows:
```
Input:
  group_by: 1-3 of ["vendor","model","region","province","olttype",
                     "network","sys_pollstatus","sitename"]
  network: string (default "FTTx"; pass "all" to widen)
  filters: vendor/region/province/olttype/pollstatus (optional, same as device_search)
  top_n: int (default 20, max 100)
Output:
  rows: [{ <group_by cols>, device_count }]   -- ordered by device_count DESC
  group_count_total: int   -- how many distinct groups matched, before top_n cut
  truncated: bool
```
Example: `device_stats(group_by=["vendor","model","sitename"], top_n=20)` →
the 20 highest-count vendor/model/sitename combos, with
`group_count_total: 10608, truncated: true`.

**`device_uplinks`** *(thin Phase-1 slice of topology, no join to `topo` yet)*
— surfaces the homing/uplink columns already sitting on `device` itself
(`a_homing_id/site`, `b_homing_id/site`, `c_homing_id/site`, `uplink_ip1/2`,
`uplink_model1/2`, `uplink_site1/2`, `ringid`, `ringtopo`).
```
Input: exactly one of { id: int } | { ip: string } | { name: string }
Output: the homing/uplink/ring columns for that device, same not-found/
        ambiguous shape as device_get
```

That's 3 read tools + 1 uplink-detail tool + resources. Deliberately not
exposing `INSERT`/`UPDATE`/`DELETE` — the DB role can't do them anyway
(`pmsonline_ro` is SELECT-only), but the tool surface shouldn't even offer the
shape of a write.

### Phase 2 (once Phase 1 is validated)
- `intf_list` / `intf_get` (interfaces per device, via `intf.device_id`)
- `device_neighbors` (via `topo` — physical link topology)
- `device_alarms` / `device_reboot_events` (via `olt_alarm_raw`,
  `device_reboot_event`) — operational/health questions
- `device_traffic_summary` (via `olt_traffic1d` / `capfttx1d` — careful here,
  these are the tables closest to the weekly-partition explosion; needs its
  own date-range-bounded design, not a naive join)

### Explicitly deferred / needs a separate design pass
- Anything under `bras_*`, `fttx_subscriber`, `cpe_map`, `radius_callingid` —
  subscriber-identifying data. Should get its own access review before any
  MCP tool touches it, independent of this device-inventory design.

## 5. Server implementation

- **Language/stack**: Python, matching the repo's existing convention
  (`app/pgadm` uses `uv` + `psycopg2`). Use the official `mcp` Python SDK
  (`pip install mcp`, or `uv add mcp`) with `psycopg2` (sync) or
  `asyncpg`/`psycopg[async]` if the SDK's async server model is used —
  recommend `psycopg` (v3) async, since the MCP Python SDK's server loop is
  asyncio-based.
- **Connection handling**: a small connection pool (`psycopg_pool`), not one
  connection per call. Each connection, on checkout, runs:
  ```sql
  SET statement_timeout = '5s';
  SET default_transaction_read_only = on;
  ```
- **Config**: env vars (`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`,
  `PGPASSWORD`) or a `.env` — never hardcode `pmsonline_ro`'s password in
  source. Add `.env` to `.gitignore` (the dev password being "shared/public"
  per the infra README is a separate DB; don't inherit that habit here).
- **Transport**: `stdio` to start (this is exactly what Claude
  Code/Desktop expects for a local MCP server — no auth surface to design
  yet). If this later needs to serve multiple users/services remotely, that's
  a distinct step up (HTTP+SSE transport, bearer auth, likely a *different*
  DB role scoped tighter than `pmsonline_ro`) — don't build it until needed.
- **Logging**: log every tool call (tool name + resolved filter args, not raw
  free text if it might contain anything sensitive) to stderr/a file for
  audit — this is network infrastructure inventory, worth being able to answer
  "what did the model query" after the fact.

## 6. Proposed project layout

```
ml/mcp/
  DESIGN.md                 <- this file
  db-create-user.sql        <- already exists
  device.sql                <- already exists (raw reference SELECT)
  pyproject.toml
  .env.example
  mcp_device/
    __init__.py
    config.py                <- env var loading (incl. DEVICE_DEFAULT_NETWORK=FTTx)
    db.py                    <- connection pool + session setup (statement_timeout, read-only)
    resources.py             <- vendor/region/olttype/network resource providers + TTL cache
    tools.py                 <- device_search / device_get / device_stats / device_uplinks
    server.py                <- MCP server entrypoint (stdio), wires tools.py to FastMCP
  README.md                  <- how to configure + run the server
```

## 7. Status

Phase 1 scope, `network='FTTx'` default, and the `device_stats` contract
(incl. `model`/`sitename` cardinality handling) are confirmed — see
[README.md](README.md) for how to configure and run it.
