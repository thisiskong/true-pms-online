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
| 7 | UPLINK-SFP | `07_uplink_sfp_raw.json` | `07_uplink_sfp_normalized.json` |
| 8 | PON-SFP | `08_pon_sfp_raw.json` | `08_pon_sfp_normalized.json` |

---

## API Call Method per Item

| # | Item | Backend | Method | Path | Auth |
|---|---|---|---|---|---|
| 3 | ES-DEVICE | ES | `POST` | `/altiplano-indexsearch/intents/_search/` | Bearer JWT |
| 4 | ES-FIBER | ES | `POST` | `/altiplano-indexsearch/intents/_search/` | Bearer JWT |
| 5 | ES-ONT | ES | `POST` | `/altiplano-indexsearch/intents/_search/` | Bearer JWT |
| 6 | SLOT-INV | AC | `GET` | `/{rel}-ac/rest/restconf/data/ibn:ibn/intent={OLT},device-mf/intent-specific-data/device-mf:device-mf` | Bearer JWT |
| 7 | UPLINK-SFP | ES+AC | `POST` (ES) + `POST` (AC action) | ES: `/altiplano-indexsearch/intents/_search/` (filter `uplink-connection`)<br>AC: `/{rel}-ac/rest/restconf/data/ibn:ibn/intent={uplink-name},uplink-connection/intent-specific-data/sfp-status:show-sfp-diagnostics-and-inventory` | Bearer JWT |
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
- `intent={OLT},device-mf` → `device-mf:device-mf` (GET)
- `intent={uplink-name},uplink-connection` → `sfp-status:show-sfp-diagnostics-and-inventory` (POST action, body: `{"sfp-status:input": {"entity": "<port-id>"}}`)
- `intent={fiber},fiber` → `fiber:fiber` (GET)

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
        +-- UPLINK-SFP (7)
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
| 7 | UPLINK-SFP | ES-DEVICE (3) | OLT names → ES query for `uplink-connection` intent → port-ids for SFP action |
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
| 7 | UPLINK-SFP — uplink SFP details | ES+AC | Done | ES query for `uplink-connection` intent → `sfp-status:show-sfp-diagnostics-and-inventory` POST action; 2 ports per OLT (nt-a:xfp:1, nt-b:xfp:1) |
| 8 | PON-SFP — PON SFP inventory | AC | Done | via `fiber:fiber` GET; `vendorpn` parsed from `model_name` |
| 9 | RC-INTF — uplink interface list | RC | Blocked | RC-Proxy URL prefix not confirmed |
| 10 | RC-INTF-ONE — PON port state | RC | Blocked | depends on RC-Proxy |

### Open blockers
- **Items 9, 10** require Nokia to confirm the correct RC-Proxy URL prefix for this Altiplano instance. All tested prefixes return 404. The RC-Proxy microservice (`nokia-altiplano-rcdeviceproxy`) does not appear to be deployed on `10.50.238.203` — Nokia needs to confirm the host/port or whether the service is enabled.
- Only `ifindex` in `ponport.jsonl` remains `NotImplement` pending RC-Proxy. `ifadmin` and `ifoper` are now populated from AC/ES data (see below).

### `ifadmin` and `ifoper` — resolved without RC-Proxy
- **`ifadmin`**: sourced from `fiber:fiber` AC GET (`pon-port[].admin-state`). `unlocked`→`up`, `locked`→`down`, absent→`up` (YANG default).
- **`ifoper`**: sourced from ES fiber intent `required-network-state`. `active`→`up`, others→`down`. Note: this reflects the *intent* state, not live device operational state — live state requires RC-Proxy.
- **`ifindex`**: still `NotImplement` — only available from RC-Proxy `if-index` field.

### Item 7 — resolution note
Previously assumed to use `eqpt:show-uplink-sfp-diag-inv` via RC-Proxy (blocked on fw 25.6). Actually uses:
1. ES query with `intent-type: uplink-connection` and `target.device-name` filter → get uplink intent name + `port-id` list
2. AC POST action `sfp-status:show-sfp-diagnostics-and-inventory` with body `{"sfp-status:input": {"entity": "<port-id>"}}` — same AC backend as items 6 and 8, no RC-Proxy required.

---

## Field Mapping

Value conventions used in all output tables:
- **populated** — real value from Nokia NBI
- `"NotImplement"` — Nokia NBI has this data but endpoint is blocked or not yet implemented
- `"NotSupported"` — Nokia NBI has no equivalent; requires external source (SNMP, LLDP, manual mapping)

---

### device.jsonl

One row per OLT device.

| Field | Value / Source | Remark |
|---|---|---|
| `name` | ES-DEVICE: `target.device-name` | |
| `ip` | ES-DEVICE: `configuration.ip-address[0]` | |
| `vendor` | Hardcoded `"Nokia"` | |
| `descr` | SLOT-INV: `hardware-type` → ES-DEVICE fallback | Hardware type string e.g. `LS-MF-LANT-A` |
| `olttype` | Mapped from `descr` via `HARDWARE_TYPE_TO_OLTTYPE` | e.g. `MF-2`, `DF-16GM` |
| `swversion` | SLOT-INV: `swversion` → ES-DEVICE: `configuration.device-version[0]` | |
| `transport_protocol` | SLOT-INV: `transport-protocol` field | e.g. `xgs-pon` |
| `lt_slots` | SLOT-INV: list of board slot names | e.g. `["LT1", "LT2"]` |
| `agent` | Hardcoded `"altiplano"` | Identifies the collection agent |
| `sys_pollstatus` | ES-DEVICE: `required-network-state == "active"` → `1` else `0` | Intent state, not live device poll status |
| `usr_pollstatus` | Hardcoded `1` | |
| `pollint` | Hardcoded `86400` | Seconds (24h) |
| `last_modify_by` | Hardcoded `"nokia-discovery"` | |
| `last_modify_at` | Discovery run timestamp (UTC) | |
| `lastseen` | Discovery run timestamp (UTC) | Not a live heartbeat |
| `first` | Discovery run timestamp (UTC) | |
| `model` | `NotImplement` | Available via `eqpt:slot-inventory` → Chassis model; blocked on fw 25.6 |
| `chassisid` | `NotImplement` | Available via `eqpt:slot-inventory` → Chassis serial number; blocked on fw 25.6 |
| `pn` | `NotImplement` | Available via `eqpt:slot-inventory` → Chassis part code; blocked on fw 25.6 |
| `network` | `NotSupported` | Static topology config — not in Altiplano NBI |
| `region` | `NotSupported` | Static site mapping — not in Altiplano NBI |
| `province` | `NotSupported` | Static site mapping — not in Altiplano NBI |
| `sitename` | `NotSupported` | Static site mapping — not in Altiplano NBI |
| `latitude` | `NotSupported` | Static site coordinates — not in Altiplano NBI |
| `longitude` | `NotSupported` | Static site coordinates — not in Altiplano NBI |
| `sysuptime` | `NotSupported` | SNMP OID 1.3.6.1.2.1.1.3.0 only — no equivalent in Altiplano |
| `community` | `NotSupported` | SNMP community string — external credential store |
| `dn` | `NotSupported` | Domain name — not in Altiplano |
| `hop` | `NotSupported` | Network hop count — not in Altiplano |
| `rn` | `NotSupported` | Ring node ID — static topology config |
| `ringid` | `NotSupported` | Ring ID — static topology config |
| `ringtopo` | `NotSupported` | Ring topology type — static topology config |
| `topology` | `NotSupported` | Static topology config — not in Altiplano |
| `uplink_ip1` | `NotSupported` | Upstream device IP — requires LLDP or manual mapping |
| `uplink_ip2` | `NotSupported` | Secondary uplink IP — requires LLDP or manual mapping |
| `uplink_model1` | `NotSupported` | Upstream device model — requires LLDP or manual mapping |
| `uplink_model2` | `NotSupported` | Secondary uplink model — requires LLDP or manual mapping |
| `uplink_site1` | `NotSupported` | Upstream site — requires manual mapping |
| `uplink_site2` | `NotSupported` | Secondary uplink site — requires manual mapping |
| `a_homing_id` | `NotSupported` | Aggregation homing ID — static topology config |
| `a_homing_site` | `NotSupported` | Aggregation homing site — static topology config |
| `b_homing_id` | `NotSupported` | Backup homing ID — static topology config |
| `b_homing_site` | `NotSupported` | Backup homing site — static topology config |
| `c_homing_id` | `NotSupported` | Static topology config |
| `c_homing_site` | `NotSupported` | Static topology config |

---

### intf.jsonl

One row per uplink interface. Currently one placeholder row per OLT — real rows require RC-Proxy (item 9).

| Field | Value / Source | Remark |
|---|---|---|
| `device_ip` | ES-DEVICE: `configuration.ip-address[0]` | |
| `device_name` | ES-DEVICE: `target.device-name` | |
| `iftype` | Hardcoded `"ethernetCsmacd"` | Fixed for all uplink ethernet ports |
| `sys_pollstatus` | Hardcoded `1` | |
| `usr_pollstatus` | Hardcoded `1` | |
| `last_modify_by` | Hardcoded `"nokia-discovery"` | |
| `last_modify_at` | Discovery run timestamp (UTC) | |
| `lastseen` | Discovery run timestamp (UTC) | |
| `first` | Discovery run timestamp (UTC) | |
| `id` | `NotImplement` | Composite key `{device.id}.{ifindex}` — requires RC-Proxy |
| `device_id` | `NotImplement` | FK from device table — requires RC-Proxy |
| `ifname` | UPLINK-SFP: `port_id` (e.g. `nt-a:xfp:1`) | One row per uplink port |
| `ifdescr` | Same as `ifname` | Nokia NBI has no separate description for uplink port |
| `ifspeed` | `NotImplement` | RC-Proxy: `interface[].speed` |
| `ifadmin` | UPLINK-SFP: `sfp-status:output.inventory[].admin-status` | `disable`→`down`, else `up`; `NotImplement` if SFP absent |
| `ifoper` | UPLINK-SFP: `sfp-status:output.inventory[].oper-status` | `NotImplement` if SFP slot unpopulated (e.g. QCENGNKMF2) |
| `ifindex` | `NotImplement` | RC-Proxy: `interface[].if-index` |
| `ifphyaddr` | `NotImplement` | RC-Proxy: `interface[].phys-address` (MAC) |
| `ifalias` | `NotImplement` | RC-Proxy: `interface[].description` |
| `ifconn` | `NotImplement` | Derived from `ifoper` — requires RC-Proxy |
| `name` | UPLINK-SFP: composite `{device_name}:{port_id}` | e.g. `SMK01058GO0:nt-a:xfp:1` |
| `moduleclass` | UPLINK-SFP: derived from `port_id` token (`xfp`→`10GE-XFP`, `qsfp`→`100GE-QSFP28`) | Populated from port name type — not from SFP inventory directly |
| `vendorpn` | UPLINK-SFP: `sfp-status:output.inventory[].part-number` (first token) | `None` if SFP slot unpopulated (e.g. QCENGNKMF2) |
| `mediatype` | UPLINK-SFP: derived from `wave-length` (`1310`→`SM`, `850`→`MM`) | `None` if SFP slot unpopulated |
| `altname` | `NotSupported` | Optional alternate name — not in Altiplano NBI |
| `dstport` | `NotSupported` | Neighbor port — requires LLDP or manual mapping |
| `dstsite` | `NotSupported` | Neighbor site — requires manual mapping |
| `dsttype` | `NotSupported` | Neighbor device type — requires manual mapping |
| `dstname` | `NotSupported` | Neighbor device name — requires LLDP or manual mapping |
| `dstsite2` | `NotSupported` | Secondary neighbor site — requires manual mapping |
| `dsttype2` | `NotSupported` | Secondary neighbor device type — requires manual mapping |
| `remdstsite` | `NotSupported` | Remote destination site — requires manual mapping |

> **Note on `intf` row count**: One row per uplink port discovered via UPLINK-SFP item 7. Testbed has 2 ports per OLT × 2 OLTs = 4 rows. QCENGNKMF2 ports have no SFP inventory (empty slots), so `vendorpn`, `mediatype`, and `ifoper` are `None`/`NotImplement`.

---

### ponport.jsonl

One row per fiber/PON port (48 total: 16 for QCENGNKMF2, 32 for SMK01058GO0).

| Field | Value / Source | Remark |
|---|---|---|
| `device_name` | ES-DEVICE: `target.device-name` | OLT name |
| `device_ip` | ES-DEVICE: `configuration.ip-address[0]` | |
| `ifname` | ES-FIBER: `target.fiber-name` | e.g. `QCENGNKMF2-1-16` |
| `ifdescr` | Same as `ifname` | Nokia NBI has no separate description field for fiber |
| `ponport` | Parsed from ES-FIBER `configuration.pon-id[0]` (`LT1.PON16` → `1-1-1-16`) | Falls back to parsing fiber name if pon-id absent |
| `iftype` | ES-FIBER: `configuration.xpon-type[0]` mapped via `XPON_TYPE_MAP` | `gpon`/`xgs-pon`/`mpm-gpon-xgs` → `gpon`/`xgs-pon` |
| `ifspeed` | ES-FIBER: `xpon-type` mapped to bps | `gpon`=2488000000, `xgs-pon`=10000000000 |
| `l1_dl_max_bw` | ES-FIBER: `xpon-type` mapped to Mbps | `gpon`=2488, `xgs-pon`=10240 |
| `l1_ul_max_bw` | ES-FIBER: `xpon-type` mapped to Mbps | `gpon`=1244, `xgs-pon`=10240 |
| `l1sp` | ES-FIBER: `configuration.port-profile[0]` | Line speed profile name |
| `xpon_type` | ES-FIBER: `configuration.xpon-type[0]` raw value | e.g. `mpm-gpon-xgs` |
| `pon_id` | ES-FIBER: `configuration.pon-id[0]` | e.g. `LT1.PON16` |
| `name` | Composite `{device_name}:{ponport}` | e.g. `QCENGNKMF2:1-1-1-16` |
| `moduleclass` | PON-SFP: `fiber:fiber` → `pon-port[].xpon-type` mapped via `XPON_TO_MODULECLASS` | e.g. `GPON/XGS-PON (combo)` |
| `vendorpn` | PON-SFP: `fiber:fiber` → `pon-port[].model-name` — part number parsed from `(XXXXXXXX)` at end of string | e.g. `3FE47581BD` |
| `model_name` | PON-SFP: `fiber:fiber` → `pon-port[].model-name` full string | e.g. `XGS/GPON SFP-DD C+ (I-temp) OLT MPM GEN2 (3FE47581BD)` |
| `ifconn` | ES-ONT: count of ONTs on this fiber | Total ONT count per fiber from ES size=0 agg |
| `sys_pollstatus` | Hardcoded `1` | |
| `usr_pollstatus` | Hardcoded `1` | |
| `last_modify_by` | Hardcoded `"nokia-discovery"` | |
| `last_modify_at` | Discovery run timestamp (UTC) | |
| `lastseen` | Discovery run timestamp (UTC) | |
| `first` | Discovery run timestamp (UTC) | |
| `ifadmin` | PON-SFP: `fiber:fiber` → `pon-port[].admin-state` | `unlocked`→`up`, `locked`→`down`, absent→`up` (YANG default). Not the same as live device admin state via RC-Proxy. |
| `ifoper` | ES-FIBER: `required-network-state` | `active`→`up`, others→`down`. **Reflects intent state, not live device oper state.** Live oper state requires RC-Proxy (item 10 — blocked). |
| `id` | `NotImplement` | Composite key `{device.id}.{ifindex}` — requires RC-Proxy |
| `device_id` | `NotImplement` | FK from device table — requires RC-Proxy |
| `ifindex` | `NotImplement` | RC-Proxy: `ietf-interfaces:interface.if-index` |
| `dl_bw_remaining` | `NotImplement` | OpenTSDB PON utilization counter — requires §4.2.15 (Enable PON Utilization Monitoring) to be enabled on device |
| `ul_bw_remaining` | `NotImplement` | OpenTSDB PON utilization counter — same prerequisite as `dl_bw_remaining` |
| `ifphyaddr` | `NotSupported` | PON ports have no MAC address |
| `ifalias` | `NotSupported` | Not applicable for PON ports |

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
