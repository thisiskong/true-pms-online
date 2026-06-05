# Nokia Altiplano NBI — Device Discovery

Python scripts to discover Nokia Altiplano NBI endpoints and collect device, fiber, ONT, slot, and SFP inventory data.

---

## Setup

```bash
uv sync
```

---

## Running the Script

### Full discovery (all items at once)
```bash
uv run python discover.py --server 10.50.238.203 --password password --no-verify-ssl
```

### All arguments
```bash
uv run python discover.py \
  --server 10.50.238.203 \
  --username adminuser \
  --password password \
  --rel nokia-altiplano \
  --no-verify-ssl \
  --output-dir output
```

| Argument | Default | Description |
|---|---|---|
| `--server` | required | Altiplano server IP or hostname |
| `--username` | `adminuser` | Login username |
| `--password` | required | Login password |
| `--rel` | `nokia-altiplano` | Release name prefix used in AC URLs |
| `--no-verify-ssl` | off | Disable TLS verification (needed for testbed) |
| `--output-dir` | `output` | Directory to save JSON files |

---

## Output Files per Item

Each item saves two files to `--output-dir`:

| # | Item | Raw file | Normalized file |
|---|---|---|---|
| 3 | ES-DEVICE | `03_es_device_raw.json` | `03_es_device_normalized.json` |
| 4 | ES-FIBER | `04_es_fiber_raw.json` | `04_es_fiber_normalized.json` |
| 5 | ES-ONT | `05_es_ont_raw.json` | `05_es_ont_normalized.json` |
| 6 | SLOT-INV | `06_slot_inv_raw.json` | `06_slot_inv_normalized.json` |
| 8 | PON-SFP | `08_pon_sfp_raw.json` | `08_pon_sfp_normalized.json` |

---

## API Call Method per Item

| # | Item | Backend | Method | Path | Auth |
|---|---|---|---|---|---|
| 3 | ES-DEVICE | ES | `POST` | `/altiplano-indexsearch/intents/_search/` | Bearer JWT |
| 4 | ES-FIBER | ES | `POST` | `/altiplano-indexsearch/intents/_search/` | Bearer JWT |
| 5 | ES-ONT | ES | `POST` | `/altiplano-indexsearch/intents/_search/` | Bearer JWT |
| 6 | SLOT-INV | AC | `GET` | `/{rel}-ac/rest/restconf/data/ibn:ibn/intent={OLT},device-mf/intent-specific-data/device-mf:device-mf` | Bearer JWT |
| 7 | UPLINK-SFP | AC | `GET` | `/{rel}-ac/rest/restconf/data/ibn:ibn/intent={OLT},uplink-connection/intent-specific-data/uplink-connection:uplink-connection` | Bearer JWT |
| 8 | PON-SFP | AC | `GET` | `/{rel}-ac/rest/restconf/data/ibn:ibn/intent={fiber},fiber/intent-specific-data/fiber:fiber` | Bearer JWT |
| 9 | RC-INTF | RC | `GET` | `/{rel}-rcdeviceproxy/rest/restconf/data/anv:device-manager/anv-device-holders:device={OLT}.{LT}/device-specific-data/ietf-interfaces:interfaces-state` | Bearer JWT |
| 10 | RC-INTF-ONE | RC | `GET` | `/{rel}-rcdeviceproxy/.../interfaces-state/interface={fiber-name}` | Bearer JWT |

---

## Key Differences per Backend

**ES (items 3–5)** — all three use the same URL, differentiated only by the request body:
```json
POST /altiplano-indexsearch/intents/_search/
Content-Type: application/json

{ "query": { "bool": { "filter": [{ "term": { "intent-type": "device-mf" } }] } } }
```

**AC (items 6–8)** — each uses a different intent type and YANG module path:
- `intent={OLT},device-mf` → `device-mf:device-mf`
- `intent={OLT},uplink-connection` → `uplink-connection:uplink-connection`
- `intent={fiber},fiber` → `fiber:fiber`

```
GET /{rel}-ac/rest/restconf/data/ibn:ibn/intent=...
Content-Type: application/yang-data+json
Accept: application/yang-data+json
```

**RC (items 9–10)** — live device proxy, per-LT card:
- Device name format: `{OLT}.{LT}` e.g. `QCENGNKMF2.LT1`
- Currently blocked — RC-Proxy URL prefix not confirmed

---

## Item Dependencies

```
LOGIN
  |
  +-- ES-DEVICE (3)
        |
        +-- SLOT-INV (6)
        |     |
        |     +-- RC-INTF (9)  [blocked]
        |
        +-- UPLINK-SFP (7)  [blocked]
        |
        +-- ES-FIBER (4)
              |
              +-- ES-ONT (5)
              |
              +-- PON-SFP (8)
              |
              +-- RC-INTF-ONE (10)  [blocked]
```

| # | Item | Depends on | What it needs |
|---|---|---|---|
| 3 | ES-DEVICE | LOGIN only | — |
| 4 | ES-FIBER | ES-DEVICE (3) | OLT names |
| 5 | ES-ONT | ES-FIBER (4) | Fiber names |
| 6 | SLOT-INV | ES-DEVICE (3) | OLT names |
| 7 | UPLINK-SFP | ES-DEVICE (3) | OLT names |
| 8 | PON-SFP | ES-FIBER (4) | Fiber names |
| 9 | RC-INTF | ES-DEVICE (3) + SLOT-INV (6) | OLT names + LT slot names to build device ID e.g. `QCENGNKMF2.LT1` |
| 10 | RC-INTF-ONE | ES-FIBER (4) | Fiber names |

**Items 3 and 6 can run in parallel** after login. **Items 4, 5, 8, 10 are a sequential chain.** **Item 9 needs both ES-DEVICE and SLOT-INV** to know which LT slots are populated.

---

## Progress

| # | Item | Backend | Status | Notes |
|---|---|---|---|---|
| — | Project structure + shared client | — | Done | `nokia/client.py`, output dir |
| 3 | ES-DEVICE — OLT list | ES | Done | 2 OLTs: `QCENGNKMF2`, `SMK01058GO0` |
| 4 | ES-FIBER — fiber list per OLT | ES | Done | 48 fibers total (16 + 32) |
| 5 | ES-ONT — ONT count per fiber | ES | Done | 86,896 ONTs total |
| 6 | SLOT-INV — board inventory | AC | Done | via `device-mf:device-mf` GET — `eqpt:slot-inventory` not present on fw 25.6 |
| 7 | UPLINK-SFP — uplink SFP details | AC | Blocked | `eqpt:show-uplink-sfp-diag-inv` returns `unknown-element` on fw 25.6 |
| 8 | PON-SFP — PON SFP inventory | AC | Done | via `fiber:fiber` GET; `vendorpn` parsed from `model_name` |
| 9 | RC-INTF — uplink interface list | RC | Blocked | RC-Proxy URL prefix not confirmed |
| 10 | RC-INTF-ONE — PON port state | RC | Blocked | depends on RC-Proxy |

### Open blockers
- **Items 7, 9, 10** require Nokia to confirm correct URL prefix and YANG action paths for firmware 25.6.

---

## Authentication

Login endpoint (testbed):
```
POST https://10.50.238.203/nokia-altiplano-ac/rest/auth/login
Authorization: Basic <base64(username:password)>
```

Response fields: `accessToken` (expires 1800s), `refreshToken` (expires 86400s).

Refresh endpoint:
```
POST https://10.50.238.203/nokia-altiplano-ac/rest/auth/refreshAccessToken
Authorization: Bearer {refreshToken}
```

Standalone auth script:
```bash
# Print access token only
uv run python main.py --server 10.50.238.203 --password password --no-verify-ssl

# Full JSON response
uv run python main.py --server 10.50.238.203 --password password --no-verify-ssl --output json

# Refresh token
uv run python main.py --server 10.50.238.203 --password x --refresh-token <TOKEN> --no-verify-ssl
```
