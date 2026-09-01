# pmsonline-device-mcp

Read-only MCP server exposing FTTx device inventory (`pmsonline.device`) to
LLM clients (Claude Code, Claude Desktop, etc.). See [DESIGN.md](DESIGN.md)
for the full design rationale.

## Setup

```
cp .env.example .env
# edit .env if needed — defaults already point at dv01/pmsonline/pmsonline_ro
uv sync
```

## Run standalone (for testing)

```
uv run mcp dev mcp_device/server.py
```

Opens the MCP Inspector so you can call `device_search`, `device_get`,
`device_stats`, `device_uplinks` and browse the `device://*` resources by
hand.

## Register with Claude Code

```
claude mcp add pmsonline-device -- uv --directory <absolute-path-to-ml/mcp> run pmsonline-device-mcp
```

(or add an equivalent entry to Claude Desktop's `claude_desktop_config.json`
pointing at the same command.)

## Scope

- **Read-only.** DB role `pmsonline_ro` is SELECT-only at the grant level
  (see [db-create-user.sql](db-create-user.sql)); the server additionally
  forces `readonly=True` + a 5s `statement_timeout` on every connection.
- **Device inventory only** (Phase 1). No interfaces, topology joins, alarms,
  traffic, or subscriber/BRAS data yet — see DESIGN.md §4 for the phased
  roadmap.
- **Defaults to `network='FTTx'`** on every multi-row tool. Pass
  `network="all"` to widen a query to IPRAN/BMA/other segments.
