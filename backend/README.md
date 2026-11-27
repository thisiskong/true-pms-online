# PMS Online prototype — backend

FastAPI service with three entry points over one read-only data layer:

| Path | What |
|---|---|
| `/api/*` | REST API for the React app (device list, dashboard, CSV export, fleet stats) |
| `/api/chat` | Claude chat, one turn per POST, streamed as Server-Sent Events |
| `/mcp` | MCP server (Streamable HTTP, bearer token) exposing the same tools to Claude Desktop / Claude Code |

Design: [`../docs/architecture.md`](../docs/architecture.md).

## Run

```bash
cd backend
cp .env.example .env          # set PG_DSN password, ANTHROPIC_API_KEY, MCP_TOKENS
uv sync
uv run uvicorn app.main:app --port 8000 --reload
```

- OpenAPI docs: http://localhost:8000/docs
- If `../frontend/dist` exists (after `npm run build`), the backend also serves the React app at http://localhost:8000/.
- The chat needs `ANTHROPIC_API_KEY` (Claude API usage is billed to the key's Console organization). Everything else works without it.

## Tests

```bash
uv run pytest -q
```

- `test_chat_loop.py`: orchestrator with a fake Claude client (no network).
- `test_db_integration.py`: real read-only DB (skipped if unreachable). Verifies sessions are read-only and writes fail.
- `test_readonly_code.py`: static guard, no write/DDL SQL anywhere in `app/`.

## Layout

```
app/
  main.py         ASGI dispatcher: /mcp (token check) -> MCP app, everything else -> FastAPI
  config.py       settings from env/.env
  db.py           asyncpg pool; every connection: default_transaction_read_only=on, statement_timeout
  queries/        ALL SQL (parameterized, whitelisted sort/filter columns, never selects device.community)
  api/            REST routers (thin)
  tools/          tool registry: Pydantic input model + handler per tool, shared by chat and MCP
  chat/           Claude streaming tool-use loop, system prompt, in-memory sessions
  mcp_server/     MCPServer registering the tool registry + resources + prompts
```

## Read-only guarantees

1. Role `pmsonline_ro` (SELECT only).
2. Every pooled connection sets `default_transaction_read_only = on` and `statement_timeout = 15s`.
3. No write SQL in code (enforced by a test). No endpoint or tool accepts raw SQL. All tool outputs are row-capped and size-capped (20 KB).

## MCP client setup

Claude Code (`.mcp.json` or `claude mcp add`):

```json
{ "mcpServers": { "pms": { "type": "http", "url": "http://<host>:8000/mcp",
    "headers": { "Authorization": "Bearer <one of MCP_TOKENS>" } } } }
```

Tools (all read-only): `search_devices`, `get_device`, `count_devices`, `list_filter_values`, `get_device_uptime`,
`list_recent_reboots`, `list_unreachable_devices`, `interface_summary`, `list_interfaces`, `get_interface`,
`find_neighbors`, `list_interface_changes`, `top_flapping_interfaces`, `fleet_overview`, `describe_schema`, `find_by_accessid`,
`fiber_overview`, `list_fiber_suspects`, `fiber_device_tree`, `list_fiber_onus`, `get_onu_fiber_score`.
Resources: `pms://schema`, `pms://device/{id}`. Prompts: `investigate_device`, `region_health`.

## Chat settings (`.env`)

| Var | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic` (Claude API direct, `ANTHROPIC_API_KEY`) or `openrouter` (`OPENROUTER_API_KEY`) |
| `OPENROUTER_MODEL` | `anthropic/claude-opus-5.5` | any OpenRouter model id that supports tools |
| `CHAT_MODELS` | built-in list | comma-separated model ids offered in the chat's model drop-down (default model is always first) |
| `OPENROUTER_PROXY` | (none) | proxy for OpenRouter calls only, e.g. `socks5://127.0.0.1:1080` |
| `CHAT_MODEL` | `claude-opus-5-5` | |
| `CHAT_EFFORT` | `medium` | `low` is cheaper/faster; evaluate before switching |
| `CHAT_FALLBACKS` | `default` | server-side refusal fallback (beta); `off` to disable |

Python code in this project uses **2-space indentation**.

### OpenRouter behind the corporate VPN

The VPN blocks openrouter.ai, so OpenRouter traffic goes through an HTTP proxy on the home LAN.
Only the OpenRouter client uses it; DB traffic is unaffected.

```bash
# .env
OPENROUTER_PROXY=http://192.168.1.16:8888
```

`socks5://host:port` also works (e.g. an SSH tunnel: `ssh -f -N -D 127.0.0.1:1080 root@pve2`).
The backend reads the proxy once at startup, so restart it after changing `OPENROUTER_PROXY`.
When chat says "Cannot reach the LLM provider", check the proxy first.
