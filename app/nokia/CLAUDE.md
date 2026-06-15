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

```
LOGIN → ES-DEVICE (3)
          ├── SLOT-INV (6) ─────────────────────────────► device.jsonl
          ├── UPLINK-SFP (7) ──────────────────────────► intf.jsonl
          └── ES-FIBER (4)
                ├── ES-ONT (5) ──────────────────────────┐
                └── PON-SFP (8) ────────────────────────► ponport.jsonl
```

Items 9 (RC-INTF) and 10 (RC-INTF-ONE) are blocked — Nokia RC-Proxy not deployed on testbed.

### Module layout

| Module | Role |
|---|---|
| `nokia/client.py` | `AltiplanoClient` — shared HTTP client with auto token refresh; `save()` helper for raw/normalized JSON pairs |
| `nokia/es_device.py` | ES-DEVICE — OLT list via Elasticsearch POST |
| `nokia/es_fiber.py` | ES-FIBER — fiber list per OLT |
| `nokia/es_ont.py` | ES-ONT — ONT count per fiber |
| `nokia/slot_inv.py` | SLOT-INV — board/slot inventory via AC GET |
| `nokia/uplink_sfp.py` | UPLINK-SFP — uplink SFP diagnostics via ES + AC POST action |
| `nokia/pon_sfp.py` | PON-SFP — PON SFP inventory via fiber AC GET |
| `nokia/mapper.py` | Shared lookup tables (`HARDWARE_TYPE_TO_OLTTYPE`, `XPON_TYPE_MAP`, etc.) |
| `nokia/assemble.py` | Builds `device`, `intf`, `ponport` rows from all collected data and writes JSONL |
| `main.py` | Standalone auth CLI (login / refresh token) |

### API backends

- **ES** — Elasticsearch: `POST /altiplano-indexsearch/intents/_search/` differentiated by `intent-type` in body
- **AC** — Altiplano Controller: `GET`/`POST` `/{rel}-ac/rest/restconf/data/ibn:ibn/intent=...`
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
