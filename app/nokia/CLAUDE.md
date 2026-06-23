# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run discovery (full inventory pull from Nokia Altiplano NBI)
uv run python discover.py --server <IP> --password <pass> --no-verify-ssl

# Auth token only
uv run python main.py --server <IP> --password <pass> --no-verify-ssl

# Refresh access token
uv run python main.py --server <IP> --password <pass> --refresh-token <TOKEN> --no-verify-ssl
```

Python 3.12+. Use 2-space indentation.

## Architecture

This project collects Nokia Altiplano NBI data for a PMS (Performance Management System). Two concerns:

**1. Discovery** — pulls inventory from the Nokia Altiplano NBI and assembles three JSONL output tables (`device.jsonl`, `intf.jsonl`, `ponport.jsonl`).

**2. PM Collection** — consumes Kafka messages and transforms them into hourly PM output files (`traffic60m`, `oltuplink60m`, `pontraffic60m`, `oltpon60m`, `onupon60m`). See `PMDATA.md` and `PMDATA-MAPPING.md` for field specs and gaps.

### Discovery data flow

Discovery is **AC-first**: one `ac.list_intents` call enumerates every IBN intent,
which the per-domain modules partition by `intent-type` (no Elasticsearch).

```
LOGIN → AC list_intents (all intents)
          ├── AC-DEVICE  ── device-mf/device-df → config+state+boards ─► device.jsonl
          ├── UPLINK-SFP ── uplink-connection → SFP diag (AC POST) ────► intf.jsonl
          └── AC-FIBER   ── fiber (grouped by OLT prefix)
                ├── ES-ONT (5, blocked) ─────────────────────────────┐
                └── PON-SFP ── reuses AC-FIBER's fiber:fiber config ──► ponport.jsonl
```

OLTs span two intent-types: `device-mf` (modular fiber) and `device-df`
(disaggregated fiber) — both are OLTs. Items 9 (RC-INTF) and 10 (RC-INTF-ONE)
are blocked — Nokia RC-Proxy not deployed on testbed.

### Module layout

| Module | Role |
|---|---|
| `nokia/client.py` | `AltiplanoClient` — shared HTTP client with auto token refresh; `save()` helper for raw/normalized JSON pairs |
| `nokia/ac.py` | Shared AC helpers — `list_intents`, `targets_of_type`, `get_intent` (bare intent GET: config + state + required-network-state) |
| `nokia/ac_device.py` | AC-DEVICE — OLT list + per-device config/state/boards (replaces former ES-DEVICE + SLOT-INV) |
| `nokia/ac_fiber.py` | AC-FIBER — fiber list per OLT + `fiber:fiber` config (replaces former ES-FIBER); returns raw config reused by PON-SFP |
| `nokia/uplink_sfp.py` | UPLINK-SFP — uplink ports via AC intent + SFP diagnostics via AC POST action |
| `nokia/pon_sfp.py` | PON-SFP — PON SFP inventory from AC-FIBER's `fiber:fiber` config (no extra GET) |
| `nokia/es_ont.py` | ES-ONT — ONT count per fiber (blocked, not wired in) |
| `nokia/mapper.py` | Shared lookup tables (`XPON_TYPE_MAP`, etc.) and JSONL → struct mapping |
| `nokia/assemble.py` | Builds `device`, `intf`, `ponport` rows from all collected data and writes JSONL |
| `main.py` | Standalone auth CLI (login / refresh token) |

### API backends

- **AC** — Altiplano Controller (primary): `GET`/`POST` `/{rel}-ac/rest/restconf/data/ibn:ibn/...`. List all intents via `?fields=intent(target;intent-type)`; per-intent detail via the bare `intent={target},{type}` GET.
- **ES** — Elasticsearch: `POST /altiplano-indexsearch/intents/_search/`. No longer used by discovery; retained for the blocked ES-ONT path and ad-hoc queries.
- **RC** — RC-Proxy (blocked): `/{rel}-rcdeviceproxy/rest/restconf/...`

Token lifetime: `accessToken` 1800 s, `refreshToken` 86400 s. `AltiplanoClient` auto-refreshes 60 s before expiry.

### Field value conventions (`assemble.py`)

- `"NotSupported"` — no equivalent in Nokia Altiplano NBI (needs LLDP, SNMP, or manual mapping)
- `"NotImplement"` — available from Nokia API but blocked or not yet collected (mainly RC-Proxy dependent fields)

### PM output field gaps (Kafka)

Kafka covers **downstream GEM port counters** (Type 1: `ietf-interfaces:interfaces-state`) and **hardware sensors** (Type 2: `ietf-hardware:hardware-state`). Fields not available from Kafka:
- `in_octets` / `in_rate` / `in_bw` — upstream GEM stats absent from topic
- `rxpwr` / `txpwr` / `current` / `voltage` — SFP optical diagnostics absent
- `ifindex` — requires RC-Proxy or SNMP
- `ip` — needs lookup from `device.jsonl`
