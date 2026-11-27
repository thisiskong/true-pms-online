# PMS Online — New Web App Prototype: High-Level Architecture

| | |
|---|---|
| Status | Phase 1 prototype implemented (see §11) |
| Date | 2026-11-23 |
| Scope | New code only in `backend/` (API, chat, MCP) and `frontend/` (React app); design docs in `docs/`. Existing `src/` (Spring Boot) is reference only; `vue-app/` is out of scope and left untouched. |
| Data source | PostgreSQL `10.50.238.194:5432/pmsonline`, user `pmsonline_ro` (**read-only**) |
| Phase-1 tables | `device`, `device_uptime`, `intf`, `intf_rev` |

---

## 1. Goals

1. **Device list**: all devices in a table, with server-side search, filter, sort, paging and CSV export.
2. **Device dashboard**: basic information for one selected device: identity, topology, uptime/reachability, interface summary, interface table, recent interface changes.
3. **MCP server**: lets AI clients (our chatbot, Claude Desktop, Claude Code) query the same data through a small set of safe, typed tools.
4. **Chatbot web frontend**: a chat panel where users ask questions in natural language ("which Huawei OLTs in region 3 rebooted this week?") and get answers that cite the underlying data.

**Non-goals for phase 1:** writing to the database, replacing the Spring Boot app, time-series metrics (OpenTSDB), Elasticsearch logs, the PON/ONU tables.

### Hard constraints

- **The database is read-only.** The app never issues DDL or DML. This is enforced in three layers (see §7).
- The schema is owned by the existing discovery/collector pipeline, so the new app adapts to it and never migrates it.
- **The prototype is self-contained.** It does not import, reuse, build into, or modify the existing `vue-app/` directory or `src/`. All new frontend code lives in `frontend/` and all new server code lives in `backend/`.
- The database is on the internal `10.x` network, so every component that touches it runs inside that network.

---

## 2. Technology choices

| Layer | Choice | Why |
|---|---|---|
| Backend language | **Python 3.12+, FastAPI** | Mature async web framework with automatic OpenAPI output, managed with `uv`. The official MCP Python SDK and the Anthropic Python SDK are both first-class. Data-access code can be shared between the REST API and the MCP server. |
| DB driver | **asyncpg** (raw parameterized SQL, no ORM) | The tables are wide and denormalized, and the queries are mostly read-only list/aggregate queries. An ORM adds nothing, and raw SQL matches the existing report-controller style. |
| Schemas / validation | **Pydantic v2** | Response models drive the OpenAPI spec, which generates the frontend TypeScript client. |
| MCP | **`mcp` Python SDK 2.x (`MCPServer`)**, Streamable HTTP transport (stateless, JSON responses) | Standard transport that Claude Desktop/Code and our own chat service can connect to. |
| LLM | **Claude API, model `claude-opus-5-5`**, Anthropic Python SDK | Default current model. Adaptive thinking, streaming. |
| Frontend | **React 19 + TypeScript + Vite** | As requested. |
| UI kit / styling | **Tailwind CSS v4** + a few hand-written components (`components/ui.tsx`) | Utility-first styling; no UI framework dependency. |
| Tables | Small custom `DataTable` + **TanStack Query** | All paging/sorting/filtering is server-side, so a headless table library adds little. Handles 50k devices and 7.5k-interface devices without loading everything. |
| Charts | **ECharts** (`echarts-for-react`) | Handles large series and rich interactions well; familiar to the team from the current dashboards. |
| Chat UI | Custom React components + **SSE** streaming | A small surface. Avoids pulling in a chat framework for a prototype. |
| API client | Hand-written `fetch` wrapper + `api/types.ts` mirroring the Pydantic models | Small surface for phase 1; switch to `openapi-typescript` generation if the API grows. |

**Alternative considered: Node.js (Fastify + `pg`).** It is viable, and the MCP and Anthropic SDKs exist for TypeScript too. Python wins here because of FastAPI's built-in OpenAPI generation, `uv` tooling, and the team's familiarity with Python for data work. Python files use **2-space indentation** (project rule).

---

## 3. System context

```
                         ┌───────────────────────── internal network ─────────────────────────┐
                         │                                                                     │
 ┌──────────────┐  HTTPS │  ┌──────────────────────┐        ┌──────────────────────────────┐   │
 │  Browser     │────────┼─▶│  frontend (static)   │        │  PostgreSQL pmsonline         │   │
 │  React SPA   │        │  │  nginx / FastAPI     │        │  device, device_uptime,       │   │
 └──────┬───────┘        │  └──────────────────────┘        │  intf, intf_rev               │   │
        │ /api/*  (JSON) │                                   └──────────────▲───────────────┘   │
        │ /api/chat (SSE)│  ┌─────────────────────────────────────────┐     │ read-only         │
        └────────────────┼─▶│  backend  (FastAPI, uvicorn)            │     │ pmsonline_ro      │
                         │  │                                         │     │                   │
                         │  │  api/      REST: devices, dashboard     │     │                   │
                         │  │  chat/     chat orchestrator (Claude)   │     │                   │
                         │  │  mcp_server/ MCP server (/mcp)          │     │                   │
                         │  │  ─────────────────────────────────────  │     │                   │
                         │  │  queries/  shared read-only data layer ─┼─────┘                   │
                         │  └──────────────┬──────────────────▲───────┘                         │
                         │                 │ HTTPS            │ MCP (Streamable HTTP, token)    │
                         └─────────────────┼──────────────────┼─────────────────────────────────┘
                                           ▼                  │
                                ┌───────────────────┐   ┌─────┴────────────────────┐
                                │ Anthropic API     │   │ Claude Desktop / Claude   │
                                │ claude-opus-5-5   │   │ Code on engineer laptops  │
                                └───────────────────┘   │ (VPN)                     │
                                                        └──────────────────────────┘
```

**One backend process, three entry points**, all built on one shared `queries/` layer:

- **REST API**: used by the device list and dashboard pages.
- **Chat orchestrator**: runs the Claude tool-use loop and streams answers to the browser.
- **MCP server**: exposes the same queries as MCP tools to external AI clients.

The chat orchestrator calls the query layer **in-process** rather than over MCP (see §6.3). That way there is one implementation of every query, and it is tested once.

When load or security requires it, the MCP server can be split into its own process with no code changes, because it only depends on `queries/`.

---

## 4. Data model (phase 1)

These are the real columns and indexes, read from `information_schema`. Row counts are approximate as of 2026-11-23.

### 4.1 Tables

| Table | Rows | Key | Purpose |
|---|---|---|---|
| `device` | ~50.7k | `id` (bigint); unique `(ip, chassisid)` | Inventory: identity, vendor/model, location, topology hierarchy, poll status |
| `device_uptime` | ~14.5k | `ip` | Latest uptime/reboot/ping status per IP (SNMP `engine_oids` or `nokia_altiplano`) |
| `intf` | ~2.8M | `id` = `"<device_id>.<ifindex>"` | Current interface state and LLDP neighbor. Average 59 interfaces per device, maximum about 7,568. |
| `intf_rev` | ~102k | `(id, rev)` | History of interface oper-status and speed changes. Each row is a state interval `first`…`lastseen`. |

### 4.2 Relationships

```
device (id) ──1:N──▶ intf (device_id)          indexed: intf_idx1
device (id) ──1:N──▶ intf_rev (device_id)      indexed: intf_rev_idx0
intf   (id) ──1:N──▶ intf_rev (id, rev)        pk
device (ip) ──1:0..1─▶ device_uptime (ip)      join on IP (no FK)
```

Things to know about the data:

- **`device.ip` is not unique by itself.** The unique key is `(ip, chassisid)`, so a join to `device_uptime` on `ip` can fan out. The queries pick one row with `DISTINCT ON` or `LIMIT 1`, and the API exposes `device.id` as the stable key.
- **Not every device has uptime data.** About 13.6k of 14.5k uptime rows match a device, so the join is always `LEFT JOIN`.
- `sys_pollstatus` and `usr_pollstatus` are ordinal ints (`PollStatusEnum`). Effective status = `coalesce(usr_pollstatus, sys_pollstatus)`. The API maps these to strings.
- `ifspeed` is in bit/s. `ifoper` values seen are `up` (1.61M), `down` (1.18M), `lowerLayerDown`, `dormant`, and `notPresent`.
- `device_uptime.uptime` is a PostgreSQL `interval`. Return it as seconds plus a human-readable string.
- Topology hierarchy fields: `network` (IPRAN/FTTx/BMA…), `topology` (CPE/OLT/DN/AN/PN/AGN…), `region`, `province`, `sitename`, `rn`/`pn`/`dn`, `ringid`, `uplink_ip1/2`, `a/b/c_homing_*`.
- Main vendors: Huawei, ZTE, Nokia, Fiberhome, GCOM, Dasan, and Raisecom.
- `device.community` contains SNMP community strings, which are secrets. **It is never selected** by the REST API, by the MCP tools, or by the LLM.

### 4.3 Query performance notes

- **Device list (50k rows).** Uses offset paging with `ORDER BY <col>, id`. Free-text search goes through indexed `name` and `ip`, which uses prefix `ILIKE 'x%'` on the existing btree indexes. Contains-search on unindexed columns is allowed but bounded by `statement_timeout`.
  - If contains-search turns out to be slow, the DBA could add a `pg_trgm` index. That is outside this app's control and is listed in §10.
- **Interfaces per device.** Always filtered by `device_id`, which is indexed. Paging stays server-side because one device can have up to 7.5k interfaces.
- **`intf_rev` recent changes.** Filtered by `device_id` (indexed), then sorted by `first DESC LIMIT n`.
- **Global aggregates** over `intf` (for example "count down interfaces by region") scan 2.8M rows. They are allowed only through specific aggregate tools with `statement_timeout`, and they are cached for 5 minutes.
- **Dropdown options.** Distinct values for vendor, model, network, topology, region, and province are pre-computed at startup and refreshed every 15 minutes in memory.

---

## 5. Backend design

### 5.1 Layout

```
backend/
  pyproject.toml            # uv; fastapi, uvicorn, asyncpg, pydantic-settings, mcp, anthropic, sse-starlette
  app/
    main.py                 # FastAPI app; mounts /api, /api/chat, /mcp; lifespan creates the DB pool
    config.py               # pydantic-settings: DB DSN, ANTHROPIC_API_KEY, MCP token, limits
    db.py                   # asyncpg pool (min 1, max 5), read-only session init
    queries/                # ★ shared data layer (pure async functions, SQL + Pydantic models)
      devices.py            #   list_devices, get_device, device_facets
      uptime.py             #   get_uptime, list_recent_reboots
      interfaces.py         #   list_interfaces, interface_summary
      changes.py            #   list_interface_changes
      stats.py              #   fleet aggregates (counts by vendor/topology/region…)
      models.py             #   Device, DeviceSummary, Uptime, Interface, IntfChange, Page[T]
    api/                    # REST routers (thin: validate → queries → JSON)
      devices.py
      dashboard.py
      export.py
    tools/                  # tool registry: one definition per query, reused by chat + MCP
      registry.py           #   name, description, JSON schema, handler → queries.*
    chat/
      orchestrator.py       # Claude tool-use loop, streaming → SSE
      prompts.py            # system prompt, schema primer
      sessions.py           # in-memory conversation store (prototype)
    mcp_server/
      server.py             # MCPServer; registers every tool in tools/registry.py
  tests/                    # pytest against a recorded fixture DB or the RO DB
```

### 5.2 REST API

All endpoints are `GET`, because the app is read-only. The one exception is `POST /api/chat`, which is a chat turn and does not write to the database.

| Method & path | Purpose | Notes |
|---|---|---|
| `GET /api/devices` | Paginated device list | `page`, `size` (≤200), `sort` (whitelisted cols), `order`, `q` (name/IP prefix), filters: `vendor`, `model`, `network`, `topology`, `region`, `province`, `pollstatus`, `seen_within_days` |
| `GET /api/devices/facets` | Distinct values for filter dropdowns | Cached |
| `GET /api/devices/export.csv` | Stream current filtered list as CSV | Server-side cursor, capped at 100k rows |
| `GET /api/devices/{id}` | Device detail (all non-secret columns) | 404 if missing |
| `GET /api/devices/{id}/uptime` | Latest `device_uptime` row (by device IP) | `null` when not polled |
| `GET /api/devices/{id}/interfaces/summary` | Counts by `ifoper`, `ifadmin`, speed bucket, `iftype`, LLDP-neighbor present | One aggregate query |
| `GET /api/devices/{id}/interfaces` | Paginated interface table | `q` (ifname/ifalias), `oper`, `sort` |
| `GET /api/devices/{id}/changes` | Recent `intf_rev` rows joined to `intf.ifname/ifalias` | `limit` (≤500), `since` |
| `GET /api/stats/overview` | Fleet KPIs (counts by vendor, topology, poll status; recent reboots) | Cached 5 min |
| `POST /api/chat` | One chat turn; response is `text/event-stream` | See §6 |
| `GET /api/health` | Liveness + DB ping | |

Response envelope for lists:

```json
{ "items": [ ... ], "page": 1, "size": 50, "total": 50730 }
```

`total` comes from `count(*)` using the same filters. For unfiltered requests it falls back to the cheap `pg_class.reltuples` estimate.

**Example query**, the device dashboard header:

```sql
SELECT d.id, d.name, d.ip, d.vendor, d.model, d.swversion, d.descr,
       d.network, d.topology, d.region, d.province, d.sitename,
       d.rn, d.pn, d.dn, d.ringid, d.uplink_ip1, d.uplink_site1, d.uplink_ip2, d.uplink_site2,
       d.latitude, d.longitude, d.first, d.lastseen, d.pollint,
       coalesce(d.usr_pollstatus, d.sys_pollstatus) AS pollstatus,
       u.polled_at, u.poll_method, u.uptime, u.last_reboot_at,
       u.last_ping_success_at, u.last_ping_rtt_ms
FROM device d
LEFT JOIN device_uptime u ON u.ip = d.ip
WHERE d.id = $1;
```

### 5.3 Cross-cutting concerns

- **Connection pool.** asyncpg with min 1, max 5 connections, kept small because the DB also serves the production Spring app. Every connection runs `SET default_transaction_read_only = on; SET statement_timeout = '15s'` at init.
- **SQL safety.**
  - Only parameterized queries are used.
  - Sort and filter columns are mapped through whitelists, never interpolated.
  - No endpoint or tool accepts raw SQL.
- **Caching.** An in-process TTL cache (`cachetools`) covers facets and fleet stats. TanStack Query caches on the client side.
- **Timezone.** DB timestamps are `timestamp without time zone` in Asia/Bangkok local time. The API emits ISO-8601 strings with a `+07:00` offset.
- **Observability.** Structured JSON logs. Each request log includes the route, duration, and row count. Each chat turn log includes tool calls, token usage, and latency.
- **Auth (prototype).** The app runs on the internal network only. A shared reverse proxy handles basic auth, or the phase-2 work in §9 adds LDAP. The MCP endpoint requires a bearer token regardless.

---

## 6. AI layer: tools, chat orchestrator, MCP server

### 6.1 Tool catalog (single registry)

Each tool is defined once in `tools/registry.py`. A definition has a name, a description written for the model, a Pydantic input model (`extra="forbid"`, bounded fields) that produces the JSON schema and validates every call, and a handler that calls `queries/*`. Both the chat orchestrator and the MCP server register from this list.

| Tool | Input | Returns |
|---|---|---|
| `search_devices` | `q?`, `vendor?`, `model?`, `network?`, `topology?`, `region?`, `province?`, `limit≤50` | Compact device rows: id, name, ip, vendor, model, topology, region, lastseen |
| `count_devices` | Same filters plus `group_by?` ∈ {vendor, model, network, topology, region, province, pollstatus} | Counts |
| `get_device` | `device_id` or `name` or `ip` | Full device detail plus uptime |
| `list_interfaces` | `device_id`, `oper?`, `q?`, `limit≤100` | Interface rows (ifname, ifalias, oper/admin, speed, LLDP neighbor) |
| `interface_summary` | `device_id` | Status/speed/type counts |
| `list_interface_changes` | `device_id?`, `since?` (≤30 days), `limit≤100` | `intf_rev` rows with ifname |
| `list_recent_reboots` | `since` (≤30 days), filters as `search_devices`, `limit≤100` | Devices whose `last_reboot_at ≥ since` |
| `fleet_overview` | none | Cached KPIs |
| `describe_schema` | none | Short description of the four tables and column meanings, so the model knows the vocabulary |

Design rules for tools:

- **Bounded outputs.** Every tool has a `limit` cap and returns `truncated: true` plus a `total` when there are more rows. This keeps context small and prevents dumping 2.8M rows.
- **Compact rows.** Tools return a curated subset of columns, not `SELECT *`. They never return `community`.
- **No free-form SQL tool in phase 1.** A guarded `run_readonly_sql` tool could be added later. It would need a parser-based `SELECT`-only check, an allow-list of tables, `LIMIT` injection, and a separate role with a short `statement_timeout`. It is deliberately left out of the prototype.

### 6.2 Chat orchestrator

**Approach: self-hosted tool-use loop on the Claude Messages API**, using the Anthropic Python SDK's streaming API.

```
Browser ──POST /api/chat {session_id, message}──▶ orchestrator
   ▲                                                │
   │  SSE events:                                   │ messages.stream(model="claude-opus-5-5",
   │   text_delta  (assistant tokens)               │   system=…, tools=registry, messages=history,
   │   tool_start  {name, input}                    │   thinking={type:"adaptive"},
   │   tool_end    {name, row_count, ms}            │   output_config={effort:"medium"})
   │   table       {columns, rows}  (optional)      │
   │   done        {usage}                          ▼
   │                                    stop_reason == "tool_use"?
   │                                     ├─ yes → run tool handlers in parallel (queries/*),
   │                                     │        append ALL tool_result blocks in one user msg,
   │                                     │        loop (max 8 iterations)
   └─────────────────────────────────────┴─ no  → end turn; save full response.content to session
```

Key settings and behaviors:

- **Model.** `claude-opus-5-5`.
  - On this model thinking cannot be disabled, and the default effort is `medium`, so effort is set explicitly. `medium` is the starting point for interactive Q&A, with `low` as a cheaper fallback route to test.
  - Thinking display is left at the default (omitted). The UI shows tool-call progress instead.
- **Tool choice.** Always `auto`. Forced `tool_choice` returns a 400 on this model. Every tool input is validated with its Pydantic model before running; invalid input goes back to the model as an `is_error` tool result.
- **Streaming.** Streaming is on, and the client tools set `eager_input_streaming: true`. Each tool's input is validated against its schema before it runs, and invalid input goes back as an `is_error` tool result.
- **Prompt caching.** The tool definitions and the system prompt (role, schema primer, answer style rules) are frozen and carry `cache_control`. Volatile data such as the current date goes into the user turn, not the system prompt.
- **Refusal handling.** The code checks `stop_reason` before reading content. Server-side `fallbacks: "default"` is enabled (beta `server-side-fallback-2026-07-01`) so a classifier refusal is retried automatically.
- **History.** The full `response.content` (including thinking blocks) is appended to the session, unchanged, in append-only order. The session store is in-memory with a 2-hour TTL for the prototype. Redis or Postgres would be used later, in a separate writable DB, never `pmsonline`.
- **Guardrails.**
  - A turn is capped at 8 tool iterations and 60 seconds.
  - Each tool result is truncated to about 20 KB.
  - Each user has a rate limit.
- **Answer style.** The system prompt asks the model to:
  - answer concisely;
  - show device names and IPs;
  - say which tool or data an answer came from;
  - state when results are truncated;
  - never guess numbers it did not retrieve.
- **Rich results.** When a tool returns tabular rows, the orchestrator also emits a `table` SSE event, so the UI can render a real table and link device names to the dashboard. The model's text does not need to repeat the table.

**Why not the alternatives?**

- **MCP connector on the Messages API** (Anthropic calls our MCP server over a public URL). The database and MCP server sit on the internal 10.x network. This option would require exposing them to the internet, so it is rejected.
- **Claude Managed Agents** (Anthropic-hosted agent loop and sandbox). Tools would still have to run on our side, because only our network can reach the DB. It also adds session runtime billing and a beta dependency. For a low-latency chat panel over a handful of read-only tools, a ~150-line self-hosted loop is simpler. It remains a reasonable option if the chatbot later grows into long-running investigations or scheduled reports.

### 6.3 MCP server

- Served at `/mcp` by the same process: `app.main:app` is a small ASGI dispatcher that checks the bearer token and routes `/mcp` to the MCP app and everything else to FastAPI. It only depends on `tools/` and `queries/`, so it can be split into its own process later.
- It registers **the same tool registry** as the chat orchestrator, so external AI clients see exactly the tools and limits our chatbot uses.
- **Auth.** A bearer token per client, stored in config. TLS is terminated at the reverse proxy. Access is VPN/internal only.
- **Intended clients.** Claude Desktop and Claude Code on engineers' machines, for ad-hoc investigation. Example Claude Code config:

  ```json
  { "mcpServers": { "pms": { "type": "http", "url": "https://pms-proto.internal/mcp",
      "headers": { "Authorization": "Bearer ${PMS_MCP_TOKEN}" } } } }
  ```
- **Resources (optional).** `pms://schema` (the table/column primer) and `pms://device/{id}` (a device card).

**Is the MCP server needed?** It is not needed for the in-app chatbot, which calls the tools in-process. It is worth building in phase 1 anyway, because it costs little once the registry exists and it lets the team use the data from their own AI clients.

---

## 7. Read-only enforcement (defense in depth)

| Layer | Mechanism |
|---|---|
| Database role | `pmsonline_ro`, which has SELECT-only grants (owned by the DBA) |
| Session | `default_transaction_read_only = on` set on every pooled connection; `statement_timeout = 15s` |
| Application | No INSERT/UPDATE/DELETE/DDL anywhere in the code; SQL lives only in `queries/`. A CI check greps for write keywords. No raw-SQL endpoint or tool. |
| AI layer | Tools are parameterized functions with capped limits; the model never authors SQL. Secret columns (`community`) are never selected. |

Chat sessions, user preferences, and audit logs need writable storage. In phase 1 they stay in memory. Later they go to a **separate** small database such as SQLite or a new Postgres schema on another instance, never `pmsonline`.

---

## 8. Frontend design

### 8.1 Layout

```
frontend/
  package.json            # react, react-router, @tanstack/react-query, @tanstack/react-table,
                          # tailwindcss v4, echarts-for-react, react-markdown
  vite.config.ts          # dev proxy /api → http://localhost:8000
  src/
    main.tsx, App.tsx     # router + QueryClientProvider + layout shell
    api/                  # types mirroring the backend models + fetch client
    pages/
      DeviceListPage.tsx  # /devices
      DeviceDashboard.tsx # /devices/:id
      ChatPage.tsx        # /chat (full-screen)
    components/
      DataTable/          # generic server-side TanStack table (paging, sort, column filters)
      FilterBar.tsx       # facet selects + search box, state synced to URL query string
      device/             # InfoCard, UptimeCard, InterfaceSummaryChart, InterfaceTable, ChangesTimeline
      chat/               # ChatPanel, MessageList, ToolCallChip, ResultTable, Composer
    hooks/                # useDevices, useDevice, useChatStream (SSE parser over fetch)
```

### 8.2 Pages

**Device list (`/devices`)**

- Columns: Name, IP, Vendor, Model, Network, Topology, Region, Province, Site, Poll status, Last seen. Column visibility is user-selectable and remembered in localStorage.
- Paging, sorting, and filtering all happen on the server. Filter state lives in the URL, so views can be shared.
- Also on the page: an export-CSV button, and a row click that opens the dashboard.

**Device dashboard (`/devices/:id`)**

1. **Header**: name, IP, vendor/model/sw version, poll-status badge, and "last seen X ago".
2. **Info cards**:
   - Identity: descr, chassis ID.
   - Location: region, province, site, plus a lat/long mini-map link.
   - Topology: network, topology, RN/PN/DN, ring, uplinks, homing.
3. **Uptime card**: current uptime, last reboot, last ping success and RTT, poll method, polled-at. It shows "no uptime data" when the device has no `device_uptime` row.
4. **Interface summary**: donut of `ifoper` counts, a bar chart of speed buckets, and counts of interfaces with an LLDP neighbor.
5. **Interface table**: server-paginated, with search and an oper filter.
6. **Recent interface changes**: a timeline/table from `intf_rev` showing the interface, the old and new oper/speed, and when the change happened.
7. **"Ask about this device"** button: opens the chat drawer pre-seeded with the device context.

**Chatbot (`/chat` plus a slide-over drawer on every page)**

- Streams the answer text, and shows tool-call chips such as "searching devices…" or "listing interfaces of X (412 rows)" for transparency.
- Renders `table` events as compact tables. Device names link to the dashboard.
- Provides example prompts, a new-conversation button, a stop button (aborts the fetch), and a copy-answer button.

### 8.3 Deployment of the frontend

`npm run build` produces static files. Phase 1 can serve them in either of two ways:

- FastAPI `StaticFiles` serves them, giving one container and one origin, so no CORS is needed.
- nginx serves them, with nginx also proxying `/api` and `/mcp`.

---

## 9. Deployment & environments

```
docker-compose (prototype host on internal network)
  ├─ pms-proto-api   uvicorn app.main:app --workers 2   (port 8000; /api, /api/chat, /mcp)
  └─ pms-proto-web   nginx: static React build, proxies /api and /mcp → api  (port 80/443)
```

- **Config** comes from environment variables or `.env`, which is git-ignored: `PG_DSN`, `ANTHROPIC_API_KEY`, `MCP_TOKENS`, and limits. No secrets are committed. The DB password in the brief belongs only in `.env`.
- **Outbound access.** The API container needs outbound HTTPS to `api.anthropic.com` (through the corporate proxy if one is required).
- **Local development.**
  - Backend: `uv run uvicorn app.main:app --reload --port 8000`.
  - Frontend: `npm run dev`, with Vite proxying `/api` to `:8000`.

---

## 10. Phasing & open questions

**Phase 1 (this prototype)**

1. Backend skeleton: config, the DB pool with read-only init, `queries/` for the four tables, and REST endpoints.
2. Frontend: the device list and device dashboard.
3. Tool registry, chat orchestrator with SSE, and the chat UI.
4. The MCP server mounted at `/mcp`, with token auth.
5. A small eval set of 20–30 real questions with expected answers, used to tune the prompt, tool descriptions, and effort level.

**Phase 2 candidates**

- LDAP login (reusing the HR auth endpoint used by the Spring app) plus role-based access to chat and MCP.
- More tables: PON ports, OLT and BRAS reports, and OpenTSDB metrics through a metrics tool.
- A guarded `run_readonly_sql` tool for power users.
- Persistent chat history in a separate writable store.
- Embedding the React pages in the Spring app, or replacing its pages.

**Open questions**

1. **Expected users and concurrency.** These determine the pool size and whether the MCP server should be a separate process.
2. **Can a `pg_trgm` index** on `device.name` and `intf.ifalias` be requested from the DBA? It would make contains-search fast.
3. **Is outbound access to the Anthropic API allowed** from the prototype host, or must calls go through a proxy or a cloud platform such as Bedrock or Vertex? The SDK supports all of them with only a client-class change.
4. **Data-handling policy.** Device names, IPs, and topology data would be sent to the LLM provider. This needs confirmation from security. The `community` column is already excluded.
5. **`device_uptime` coverage.** It covers about 14.5k of 50.7k devices. Are the rest expected to be absent (for example, CPEs not polled), or is that a gap to show in the UI?

---

## 11. Implementation status (2026-11-23)

Phase 1 is implemented in `backend/` and `frontend/`. Run instructions are in each folder's README.

| Item | Status |
|---|---|
| Read-only data layer (`queries/`) for `device`, `device_uptime`, `intf`, `intf_rev` | Done; verified against the live DB (typical query 40–200 ms; fleet overview ~1.3 s, cached 5 min) |
| REST API + CSV export | Done |
| Device list page, device dashboard page | Done |
| Tool registry (15 tools, see the MCP list in the backend README) | Done; shared by chat and MCP |
| MCP server at `/mcp` (+ 2 resources, 2 prompts), bearer-token auth | Done; tested with raw JSON-RPC calls |
| Chat orchestrator + SSE + chat UI (page and drawer) | Done; tested with a fake Claude client. **Not yet run against the real Claude API** (no `ANTHROPIC_API_KEY` on the dev machine). |
| Tests | 11 backend tests (chat loop with fake client, DB integration, read-only code guard) |
| Eval set of real questions | Not started; do this once the API key is available |

Differences from the original plan:
- No shadcn/ui, TanStack Table or generated API types. All tables are server-side, so small hand-written components were enough.
- The MCP SDK is version 2.x (`MCPServer`, formerly `FastMCP`).
- Tool inputs are validated with Pydantic rather than the API's `strict` mode.
- The tool catalog grew from §6.1 to 15 tools: added `list_filter_values`, `list_unreachable_devices`, `get_interface`, `find_neighbors` and `top_flapping_interfaces`, and `get_device_uptime` is now split out from `get_device`.
- Data note: some IPs belong to several `device` rows with different chassis IDs. The uptime join therefore lists each of those devices, all with the same uptime row.
