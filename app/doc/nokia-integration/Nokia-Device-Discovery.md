# Nokia Altiplano NBI — API Mapping for Device Discovery

**Purpose:** Map DB table fields (`device`, `intf`, `ponport`) to Nokia Altiplano NBI API endpoints for daily discovery.  
**Source documents:** NBI Integration Guide v0.1 (DOCX), PM & Inventory PDF (Apr 2025), KPI Excel  
**Date:** 2026-06-01

---

## Backend Architecture

Nokia Altiplano exposes **3 data backends** plus a shared auth service:

| Backend | URL Prefix | Protocol | Role |
|---|---|---|---|
| **ES** — Elasticsearch | `<server>/altiplano-elasticsearch/` | REST + JSON Query DSL | Intent & inventory index; query OLT list, fiber list, ONT list |
| **AC** — Analytics Controller | `<server>/<rel>-altiplano-ac/` | RESTCONF (YANG) | Intent-level operations; Altiplano aggregates & translates to device |
| **RC-Proxy** — RC Device Proxy | `<server>/<rel>-altiplano-rcdeviceproxy/` | RESTCONF (YANG) | Direct proxy to device NETCONF; returns live device state |
| **AUTH** — SSO | `<server>/altiplano-sso/` | OAuth2 / OpenID Connect | Issues JWT token; required by ES and AC |
| **AUTH (T&D)** — separate endpoint | TBD | TBD | Required by RC-Proxy; details not specified in doc — confirm with Nokia |

> ⚠️ **Two auth endpoints exist** (per §4.1): one for intent/ES APIs (JWT via OpenID Connect), and a separate one for T&D/RC-Proxy queries. ES and AC share the same JWT token. RC-Proxy may use a different token or credential scope.

**Key distinction — AC vs RC-Proxy:**
- **AC** operates at the *intent* level. Altiplano interprets the request, may aggregate data across cards/devices, and handles YANG translation internally. Higher abstraction.
- **RC-Proxy** passes the RESTCONF query directly through to the physical device as NETCONF/YANG. Returns raw live state. Lower-level, one device at a time.

**Endpoint key naming convention used in this document:**

| Prefix | Backend |
|---|---|
| `ES-*` | Elasticsearch |
| `SLOT-INV`, `UPLINK-SFP`, `PON-SFP` | AC (Analytics Controller) |
| `RC-INTF`, `RC-INTF-ONE` | RC-Proxy |
| `AUTH` | SSO — shared prerequisite, not a data backend |

---

## Discovery Flow Overview

```
Daily Discovery Job
│
├── Step 1: Authenticate → JWT token
│
├── Step 2: Discover all OLTs
│   └── ES Intent query (intent-type: device-mf) → device table
│
├── Step 3: For each OLT → Slot Inventory
│   └── IBN ACTION: slot-inventory → device.model, device.chassisid, device.swversion
│
├── Step 4: For each OLT → Uplink Interfaces
│   ├── RC-Proxy: interfaces-state (uplink) → intf table
│   └── IBN ACTION: show-uplink-sfp-diag-inv → intf.moduleclass, intf.vendorpn
│
└── Step 5: For each OLT → PON Ports
    ├── ES Intent query (intent-type: fiber) → ponport list
    ├── IBN ACTION: show-sfp-inventory (per fiber) → ponport.moduleclass, ponport.vendorpn
    └── RC-Proxy: interfaces-state (fiber) → ponport.ifadmin, ponport.ifoper
```

---

## Authentication

**Endpoint:** `POST https://<server>/altiplano-sso/realms/master/protocol/openid-connect/token`

```http
Headers:
  Authorization: Basic <base64(username:password)>

Response:
  access_token  → use as "Authorization: Bearer <token>" for all subsequent calls
  expires_in    → 1800 seconds (refresh before expiry)
  refresh_token → valid 86400 seconds
```

> ⚠️ Token expires in 30 min. Implement refresh logic for long-running discovery jobs.

---

## Table 1: `device` — OLT Device Discovery

### Primary API: Elasticsearch Intent Query (§4.2.12)

```http
POST http://<server>/altiplano-elasticsearch/intents/_search/
Authorization: Bearer <token>

Body:
{
  "query": {
    "bool": {
      "filter": [{ "term": { "intent-type": "device-mf" } }]
    }
  },
  "_source": ["target", "configuration", "required-network-state", "state"]
}
```

**Response path:** `hits.hits[]._source`

| DB Field | Type | API Response Path | Notes |
|---|---|---|---|
| `name` | varchar | `target.device-name` | e.g., `SWOLT000044` |
| `ip` | varchar | `configuration.ip-address[0]` | OLT management IP |
| `sys_pollstatus` | int | `required-network-state` == "active" → 1 | 0 if not active |
| `first` | timestamp | Set on first insert | |
| `lastseen` | timestamp | Set to NOW() each run | |
| `last_modify_at` | timestamp | Set to NOW() each run | |
| `last_modify_by` | varchar | Set to `"nokia-discovery"` | |

**From `configuration` object:**

| DB Field | API Response Path | Example Value |
|---|---|---|
| `swversion` | `configuration.device-version[0]` | `"22.12"` |
| `network` | Derive from `configuration.hardware-type[0]` or static | `"FTTx"` |

---

### Secondary API: Slot Inventory (§4.2.14)

```http
POST http://<server>/<releasename>-altiplano-ac/rest/restconf/data/ibn:ibn/intent={{Device Name}},device-mf/intent-specific-data/eqpt:slot-inventory
Authorization: Bearer <token>
Accept: application/yang-data+json
```

Filter inventory items where `name == "Chassis"` for device-level fields.

| DB Field | Type | API Response Path | Example |
|---|---|---|---|
| `model` | varchar | `eqpt:output.inventory[name=="Chassis"].model` | `"LMFS-A"` |
| `chassisid` | varchar | `eqpt:output.inventory[name=="Chassis"].serial-num` | `"YP2248SH002"` |
| `vendor` | varchar | Fixed: `"Nokia"` | All Altiplano devices are Nokia |
| `swversion` | varchar | `eqpt:output.inventory[name=="Board-Nta"].code` | NT board firmware code |

**Board → olttype mapping:**

| `hardware-type` in config | `olttype` value |
|---|---|
| `LS-MF-LANT-A` | `"MF-2"` (Lightspan MF-2) |
| `LS-DF-CFXR-H` | `"DF-16GM"` (Lightspan DF-16GM) |

---

### Fields to Set Statically or from Topology

| DB Field | Source | Notes |
|---|---|---|
| `olttype` | Derived from `model` or `hardware-type` | MF-2 / DF-16GM |
| `network` | Static or from Altiplano topology | e.g., `"FTTx"` |
| `region` / `province` | Static mapping by site | From site config or external reference |
| `sitename` | Static mapping or intent metadata | |
| `latitude` / `longitude` | ES intent: `geo-coordinates` field | If populated in Altiplano |
| `descr` | `configuration.hardware-type[0]` | e.g., `"LS-MF-LANT-A"` |
| `sysuptime` | SNMP OID or RC-Proxy CPU component | Optional — via OpenTSDB if needed |
| `usr_pollstatus` | Default `1` (active) | |
| `pollint` | Default e.g. `86400` (daily) | Seconds between polls |

---

## Table 2: `intf` — Uplink Interface Discovery

### Primary API: RC-Proxy Interface State

Uplink interfaces on Lightspan MF-2 are on the NT cards (NTIO boards), named `gei_x/x/x` or `xgei-x/x/x`.

```http
GET http://<server>/<releasename>-altiplano-rcdeviceproxy/rest/restconf/data/anv:device-manager/anv-device-holders:device={{LT Device Name}}/device-specific-data/ietf-interfaces:interfaces-state
Authorization: Bearer <token>
Accept: application/yang-data+json
```

Filter result: keep only interfaces where `type` == `ethernetCsmacd` AND name matches uplink pattern (`gei`, `xgei`, `ge-`, `xe-`, `100ge`).

| DB Field | Type | API Response Path | Example |
|---|---|---|---|
| `id` | varchar PK | Compose: `{device.id}.{ifindex}` | `"4083134.336068608"` |
| `device_id` | bigint FK | From `device.id` | |
| `device_ip` | varchar | From `device.ip` | |
| `device_name` | varchar | From `device.name` | |
| `ifname` | varchar | `interface[].name` | `"gei_1/3/1"`, `"xgei-1/4/4"` |
| `ifdescr` | varchar | `interface[].description` | |
| `iftype` | varchar | Fixed: `"ethernetCsmacd"` | |
| `ifspeed` | bigint | `interface[].speed` (in bps) | `10000000000` (10G) |
| `ifadmin` | varchar | `interface[].admin-status` | `"up"` / `"down"` |
| `ifoper` | varchar | `interface[].oper-status` | `"up"` / `"down"` |
| `ifindex` | varchar | `interface[].if-index` | |
| `ifphyaddr` | varchar | `interface[].phys-address` | MAC address |
| `ifalias` | varchar | `interface[].description` | Same as ifdescr if no alias |
| `lastseen` | timestamp | Set to NOW() each run | |
| `first` | timestamp | Set on first insert | |
| `last_modify_at` | timestamp | Set to NOW() each run | |
| `last_modify_by` | varchar | `"nokia-discovery"` | |

---

### Secondary API: Show Uplink Port SFP Diagnostics and Inventory (§4.2.17)

```http
POST http://<server>/<releasename>-altiplano-ac/rest/restconf/data/ibn:ibn/intent={{Device Name}},device-mf/intent-specific-data/eqpt:show-uplink-sfp-diag-inv
Authorization: Bearer <token>
Accept: application/yang-data+json
```

| DB Field | Type | API Response Path | Example |
|---|---|---|---|
| `moduleclass` | varchar | `eqpt:output.inventory[].module-class` | `"10GBASE-ZR/ZW"`, `"1000BASE-LX"` |
| `vendorpn` | varchar | `eqpt:output.inventory[].part-number` | `"SPP10EZRIDFEAL"` |
| `ifname` (join key) | — | `eqpt:output.inventory[].port-name` | Match to RC-Proxy `interface.name` |

> Match SFP inventory to interface by port name to populate `moduleclass` and `vendorpn`.

---

### Fields Not Available from Nokia API

| DB Field | Notes |
|---|---|
| `dstport`, `dstsite`, `dsttype`, `dstname` | Neighbor/destination info — requires LLDP or manual mapping |
| `dstsite2`, `dsttype2` | Secondary uplink destination — manual |
| `remdstsite` | Remote destination site — manual |
| `mediatype` | Derive from `moduleclass` (fiber/copper) |
| `ifconn` | Default `1` if `ifoper == "up"` |
| `altname` | Optional alternate name — can set same as `ifname` |
| `name` | Display name — compose from `device_name + ":" + ifname` |
| `usr_pollstatus`, `sys_pollstatus` | Default `1` |

---

## Table 3: `ponport` — PON Port Discovery

### Step 1: List All Fibers for an OLT (§4.2.13)

```http
POST http://<server>/altiplano-elasticsearch/intents/_search/
Authorization: Bearer <token>

Body:
{
  "query": {
    "bool": {
      "filter": [{ "term": { "intent-type": "fiber" } }],
      "must": [{ "match": { "configuration.device-name": "{{OLT Name}}" } }]
    }
  },
  "_source": ["target", "configuration", "required-network-state"]
}
```

**Response path:** `hits.hits[]._source`

| Field | API Response Path | Example |
|---|---|---|
| Fiber name (key) | `target.fiber-name` | `"SWOLT000044.L1P1"` |
| PON type | `configuration.xpon-type[0]` | `"mpm-gpon-xgs"`, `"gpon"`, `"xgs-pon"` |
| PON ID | `configuration.pon-id[0]` | `"LT1.PON1"` |
| OLT name | `configuration.device-name[0]` | `"SWOLT000044"` |

**Fiber name → `ponport` ID derivation:**

```
Fiber name: SWOLT000044.L1P1
             └── OLT name  └── L{LT slot}P{PON port}

ponport field: "1-1-{LT slot}-{PON port}"
  e.g., L1P1 → "1-1-1-1", L2P5 → "1-1-2-5", L13P05 → "1-1-13-5"
```

---

### Step 2: PON Admin/Oper Status via RC-Proxy (§4.3.13)

```http
GET http://<server>/<releasename>-altiplano-rcdeviceproxy/rest/restconf/data/anv:device-manager/anv-device-holders:device={{LT Device Name}}/device-specific-data/ietf-interfaces:interfaces-state/interface={{Fiber Name}}
Authorization: Bearer <token>
Accept: application/yang-data+json
```

| DB Field | Type | API Response Path | Example |
|---|---|---|---|
| `ifadmin` | varchar | `ietf-interfaces:interface.admin-status` | `"up"` / `"down"` |
| `ifoper` | varchar | `ietf-interfaces:interface.oper-status` | `"up"` / `"down"` |
| `ifindex` | varchar | `ietf-interfaces:interface.if-index` | |
| `ifname` | varchar | `ietf-interfaces:interface.name` | `"SWOLT000044.L1P1"` |

---

### Step 3: PON SFP Inventory (§4.2.8)

```http
POST http://<server>/<releasename>-altiplano-ac/rest/restconf/data/ibn:ibn/intent={{Fiber Name}},fiber/intent-specific-data/pon-sfp:show-sfp-inventory
Authorization: Bearer <token>
Accept: application/yang-data+json
```

| DB Field | Type | API Response Path | Example |
|---|---|---|---|
| `vendorpn` | varchar | `pon-sfp:output.inventory.part-number` | `"3FE47581BF"` |
| `moduleclass` | varchar | Derive from `inventory.fiber-type` + `pon-sfp:output.pon-optics[].wavelength` | See table below |
| `ifphyaddr` | varchar | N/A for PON | Leave null |

**`moduleclass` derivation from SFP inventory:**

| `fiber-type` | Wavelengths present | `moduleclass` value |
|---|---|---|
| `single-mode` | 1490nm + 1310nm | `"GPON CLASS B+"` |
| `single-mode` | 1577nm + 1270nm | `"XGS-PON"` |
| `single-mode` | both sets | `"GPON/XGS-PON (combo)"` |

---

### PON Port Field Mapping Summary

| DB Field | Type | Source | API / Logic |
|---|---|---|---|
| `id` | varchar PK | Compose | `{device.id}.{ifindex}` |
| `device_id` | bigint FK | device table | |
| `device_ip` | varchar | device.ip | |
| `device_name` | varchar | device.name | |
| `ifname` | varchar | ES fiber intent | `target.fiber-name` e.g., `SWOLT000044.L1P1` |
| `ifdescr` | varchar | Same as ifname | or RC-Proxy description |
| `iftype` | varchar | Derived from xpon-type | `"gpon"` or `"xgs-pon"` |
| `ifadmin` | varchar | RC-Proxy §4.3.13 | `"up"` / `"down"` |
| `ifoper` | varchar | RC-Proxy §4.3.13 | `"up"` / `"down"` |
| `ifindex` | varchar | RC-Proxy §4.3.13 | integer string |
| `ifphyaddr` | varchar | N/A | null for PON |
| `ifspeed` | bigint | Derived from PON type | GPON: 2488000000, XGS: 10000000000 |
| `ponport` | varchar | Derived from fiber name | `"1-1-{LT}-{PON}"` |
| `moduleclass` | varchar | §4.2.8 SFP inventory | `"GPON CLASS B+"` / `"XGS-PON"` |
| `vendorpn` | varchar | §4.2.8 SFP inventory | `"3FE47581BF"` |
| `l1_dl_max_bw` | bigint | Derived from PON type (Mbps) | GPON: `2488`, XGS-PON: `10240` |
| `l1_ul_max_bw` | bigint | Derived from PON type (Mbps) | GPON: `1244`, XGS-PON: `10240` |
| `l1sp` | varchar | From fiber intent `port-profile` | e.g., `"Default Port Profile"` |
| `ifconn` | int | Count of ONTs on this fiber | Via ES: count ont intents with `configuration.fiber-name = {{fiber}}` |
| `dl_bw_remaining` | varchar | Optional: PON utilization | §4.2.15 — enable monitoring first |
| `ul_bw_remaining` | varchar | Optional: PON utilization | §4.2.15 — enable monitoring first |
| `name` | varchar | Compose | `"{device_name}:{ponport}"` |
| `lastseen` | timestamp | Set to NOW() each run | |
| `first` | timestamp | Set on first insert | |
| `last_modify_at` | timestamp | Set to NOW() each run | |
| `last_modify_by` | varchar | `"nokia-discovery"` | |
| `sys_pollstatus` | int | Default `1` | |
| `usr_pollstatus` | int | Default `1` | |

---

## API Call Sequence Per Discovery Run

```
1. POST /altiplano-sso/.../token
   → save access_token

2. POST /altiplano-elasticsearch/intents/_search/
   Body: filter intent-type = "device-mf"
   → list of all OLT names + IPs
   → UPSERT into device (name, ip, sys_pollstatus, lastseen)

3. For each OLT:
   a. POST .../intent={{OLT Name}},device-mf/.../eqpt:slot-inventory
      → device.model (Chassis.model)
      → device.chassisid (Chassis.serial-num)
      → device.swversion (Board-Nta.code or device-version)
      → UPDATE device

   b. GET .../rcdeviceproxy/.../device={{LT Device}}/...interfaces-state
      Filter: type=ethernetCsmacd, name starts with gei/xgei/ge/xe
      → UPSERT intf (ifname, ifspeed, ifadmin, ifoper, ifindex, ifphyaddr)

   c. POST .../intent={{OLT Name}},device-mf/.../eqpt:show-uplink-sfp-diag-inv
      → UPDATE intf (moduleclass, vendorpn) by port-name match

   d. POST /altiplano-elasticsearch/intents/_search/
      Body: intent-type=fiber, device-name={{OLT Name}}
      → list of fiber names for this OLT
      → UPSERT ponport (ifname, ponport, iftype, l1_dl_max_bw, l1_ul_max_bw, l1sp)

   e. For each fiber:
      i.  GET .../rcdeviceproxy/.../interface={{fiber-name}}
          → UPDATE ponport (ifadmin, ifoper, ifindex)

      ii. POST .../intent={{fiber-name}},fiber/.../pon-sfp:show-sfp-inventory
          → UPDATE ponport (moduleclass, vendorpn)
```

---

## Key Constants and Derivations

### LT Device Name Format
```
RC-Proxy device parameter = OLT chassis name + "." + LT slot
e.g., OLT=SWOLT000044, LT1 → device = "SWOLT000044.LT1"
```

### PON type → DB field values

| Altiplano `xpon-type` | `iftype` | `l1_dl_max_bw` (Mbps) | `l1_ul_max_bw` (Mbps) | `ifspeed` (bps) |
|---|---|---|---|---|
| `gpon` | `gpon` | 2488 | 1244 | 2488000000 |
| `xgs-pon` | `xgs-pon` | 10240 | 10240 | 10000000000 |
| `mpm-gpon-xgs` (combo) | `xgs-pon` | 10240 | 10240 | 10000000000 |

### Fiber Name → `ponport` field

```python
# Fiber name: SWOLT000044.L13P05
# ponport format: {chassis}-{rack}-{lt}-{port}  →  "1-1-13-5"
import re
m = re.match(r'.*\.L(\d+)P(\d+)$', fiber_name)
lt, port = int(m.group(1)), int(m.group(2))
ponport_value = f"1-1-{lt}-{port}"
```

### vendor mapping
```
mfg-name "ALCL" → vendor = "Nokia"
```

---

## Notes and Caveats

1. **Token refresh:** JWT expires in 1800s. For large networks with many OLTs, implement token refresh mid-job.

2. **LT Device Name:** RC-Proxy queries require the per-LT device name (e.g., `SWOLT000044.LT1`). Derive from slot inventory: filter boards named `Board-LT{n}` to know which LT slots are populated.

3. **Uplink interface naming:** Nokia uses `gei_x/x/x` (1G) and `xgei-x/x/x` (10G) for Lightspan MF-2 uplinks on the NTIO boards. Filter by these patterns in RC-Proxy interface list.

4. **Multiple LT cards:** Lightspan MF-2 supports up to 14 LT slots. Must iterate per-LT device for RC-Proxy queries.

5. **PON utilization (`dl_bw_remaining`, `ul_bw_remaining`):** Requires first enabling PON utilization monitoring via §4.2.15. Then query OpenTSDB for utilization metrics. Implement as optional enrichment step.

6. **`ifconn` (connected ONT count):** Query Elasticsearch for ONT intents filtered by `configuration.fiber-name = {{fiber-name}}` and count hits.

7. **ES pagination:** For large networks, use `from` + `size` or `search_after` in Elasticsearch queries to handle >10 OLTs or >100 fibers.

8. **`intf.id` and `ponport.id` keys:** Existing data uses format `{device_numeric_id}.{ifindex}`. Maintain same format for compatibility.

9. **`moduleclass` for uplink:** The Excel KPI sheet lists uplink SFP classes like `10GBASE-ZR/ZW`, `1000BASE-LX` — these come from `show-uplink-sfp-diag-inv`. If API not available, derive from `ifspeed`: 1G → `"1000BASE"`, 10G → `"10GBASE"`.

---

## Complete Field Mapping Summary

### Backend & Authentication Summary

| Backend | URL Prefix | Auth Method | Endpoint Keys |
|---|---|---|---|
| **ES** (Elasticsearch) | `/altiplano-elasticsearch/` | JWT Bearer token (shared with AC) | `ES-DEVICE`, `ES-FIBER`, `ES-ONT` |
| **AC** (Analytics Controller) | `/<rel>-altiplano-ac/` | JWT Bearer token (shared with ES) | `SLOT-INV`, `UPLINK-SFP`, `PON-SFP` |
| **RC-Proxy** (RC Device Proxy) | `/<rel>-altiplano-rcdeviceproxy/` | Separate T&D auth ⚠️ confirm with Nokia | `RC-INTF`, `RC-INTF-ONE` |
| **AUTH** (SSO) | `/altiplano-sso/` | Basic (base64 user:pass) → returns JWT | — |

> ⚠️ **Two auth endpoints exist** (§4.1): ES and AC share the same JWT from `/altiplano-sso/`. RC-Proxy uses a **separate T&D auth endpoint** — details not documented; confirm with Nokia before implementation.

---

### Endpoint Reference

| Key | Backend | Method | Full Endpoint |
|---|---|---|---|
| `ES-DEVICE` | ES | `POST` | `/altiplano-elasticsearch/intents/_search/` — body: `filter intent-type=device-mf` |
| `ES-FIBER` | ES | `POST` | `/altiplano-elasticsearch/intents/_search/` — body: `filter intent-type=fiber, must device-name={{OLT}}` |
| `ES-ONT` | ES | `POST` | `/altiplano-elasticsearch/intents/_search/` — body: `filter intent-type=ont, must fiber-name={{fiber}}` |
| `SLOT-INV` | AC | `POST` | `/<rel>-altiplano-ac/rest/restconf/data/ibn:ibn/intent={{OLT}},device-mf/intent-specific-data/eqpt:slot-inventory` |
| `UPLINK-SFP` | AC | `POST` | `/<rel>-altiplano-ac/rest/restconf/data/ibn:ibn/intent={{OLT}},device-mf/intent-specific-data/eqpt:show-uplink-sfp-diag-inv` |
| `RC-INTF` | RC-Proxy | `GET` | `/<rel>-altiplano-rcdeviceproxy/rest/restconf/data/anv:device-manager/anv-device-holders:device={{LT-Device}}/device-specific-data/ietf-interfaces:interfaces-state` |
| `RC-INTF-ONE` | RC-Proxy | `GET` | `/<rel>-altiplano-rcdeviceproxy/.../interfaces-state/interface={{fiber-name}}` |
| `PON-SFP` | AC | `POST` | `/<rel>-altiplano-ac/rest/restconf/data/ibn:ibn/intent={{fiber}},fiber/intent-specific-data/pon-sfp:show-sfp-inventory` |

---

### `device` — All Fields

| # | db_colname | api_endpoint | api_field | processing_logic |
|---|---|---|---|---|
| 1 | `id` | N/A | N/A | Auto-generated by DB sequence |
| 2 | `name` | `ES-DEVICE` | `hits._source.target.device-name` | e.g., `"SWOLT000044"` |
| 3 | `ip` | `ES-DEVICE` | `hits._source.configuration.ip-address[0]` | OLT management IP |
| 4 | `model` | `SLOT-INV` | `eqpt:output.inventory[name=="Chassis"].model` | e.g., `"LMFS-A"` |
| 5 | `vendor` | N/A | N/A | Fixed `"Nokia"` — all Altiplano OLTs are Nokia/ALCL |
| 6 | `descr` | `ES-DEVICE` | `hits._source.configuration.hardware-type[0]` | e.g., `"LS-MF-LANT-A"` |
| 7 | `swversion` | `ES-DEVICE` | `hits._source.configuration.device-version[0]` | e.g., `"22.12"` |
| 8 | `chassisid` | `SLOT-INV` | `eqpt:output.inventory[name=="Chassis"].serial-num` | Chassis serial number |
| 9 | `olttype` | `ES-DEVICE` | `hits._source.configuration.hardware-type[0]` | Map: `LS-MF-LANT-A`→`"MF-2"`, `LS-DF-CFXR-H`→`"DF-16GM"` |
| 10 | `network` | N/A | N/A | Fixed `"FTTx"` or from static site config |
| 11 | `region` | N/A | N/A | Static mapping by OLT name prefix or site |
| 12 | `province` | N/A | N/A | Static mapping by OLT name prefix or site |
| 13 | `sitename` | N/A | N/A | Static IP/name-to-site lookup table |
| 14 | `latitude` | N/A | N/A | Static site coordinates mapping |
| 15 | `longitude` | N/A | N/A | Static site coordinates mapping |
| 16 | `sysuptime` | N/A | N/A | N/A — optionally from SNMP OID `1.3.6.1.2.1.1.3.0` if SNMP enabled |
| 17 | `community` | N/A | N/A | N/A — SNMP community string; from external credential config |
| 18 | `agent` | N/A | N/A | Fixed `"altiplano"` — identifies polling agent |
| 19 | `pn` | `SLOT-INV` | `eqpt:output.inventory[name=="Chassis"].code` | Nokia product code e.g., `"3FE75406AAAA"` |
| 20 | `dn` | N/A | N/A | N/A — domain name; not available from Altiplano |
| 21 | `hop` | N/A | N/A | N/A — network hop count; not available |
| 22 | `rn` | N/A | N/A | N/A — ring node ID; from static topology config |
| 23 | `ringid` | N/A | N/A | N/A — ring ID; from static topology config |
| 24 | `ringtopo` | N/A | N/A | N/A — ring topology type; from static topology config |
| 25 | `topology` | N/A | N/A | Fixed `"FTTH"` or from static config |
| 26 | `uplink_ip1` | N/A | N/A | N/A — upstream device IP; from LLDP or manual mapping |
| 27 | `uplink_ip2` | N/A | N/A | N/A — secondary uplink IP; from LLDP or manual mapping |
| 28 | `uplink_model1` | N/A | N/A | N/A — upstream device model; from LLDP or manual mapping |
| 29 | `uplink_model2` | N/A | N/A | N/A — secondary uplink model; from LLDP or manual mapping |
| 30 | `uplink_site1` | N/A | N/A | N/A — upstream site name; from manual mapping |
| 31 | `uplink_site2` | N/A | N/A | N/A — secondary uplink site; from manual mapping |
| 32 | `a_homing_id` | N/A | N/A | N/A — aggregation homing ID; from topology config |
| 33 | `a_homing_site` | N/A | N/A | N/A — aggregation homing site; from topology config |
| 34 | `b_homing_id` | N/A | N/A | N/A — backup homing ID; from topology config |
| 35 | `b_homing_site` | N/A | N/A | N/A — backup homing site; from topology config |
| 36 | `c_homing_id` | N/A | N/A | N/A — from topology config |
| 37 | `c_homing_site` | N/A | N/A | N/A — from topology config |
| 38 | `disc_id` | N/A | N/A | Set by discovery job (job/session ID) |
| 39 | `pollint` | N/A | N/A | Fixed `86400` (seconds; daily) |
| 40 | `sys_pollstatus` | `ES-DEVICE` | `hits._source.required-network-state` | `1` if `"active"`, else `0` |
| 41 | `usr_pollstatus` | N/A | N/A | Default `1` |
| 42 | `first` | N/A | N/A | Set to `NOW()` on first insert only; never updated |
| 43 | `lastseen` | N/A | N/A | Set to `NOW()` on every successful discovery run |
| 44 | `last_modify_at` | N/A | N/A | Set to `NOW()` on every update |
| 45 | `last_modify_by` | N/A | N/A | Fixed `"nokia-discovery"` |

---

### `intf` — All Fields

> Scope: uplink interfaces only — filter RC-Proxy interface list by name pattern (`gei`, `xgei`, `ge-`, `xe-`, `100ge`)

| # | db_colname | api_endpoint | api_field | processing_logic |
|---|---|---|---|---|
| 1 | `id` | `RC-INTF` | `interface[].if-index` | Compose: `"{device.id}.{ifindex}"` — matches existing PK format |
| 2 | `device_id` | N/A | N/A | FK from `device.id` matched by OLT IP |
| 3 | `device_ip` | N/A | N/A | From `device.ip` |
| 4 | `device_name` | N/A | N/A | From `device.name` |
| 5 | `ifname` | `RC-INTF` | `interface[].name` | e.g., `"gei_1/3/1"`, `"xgei-1/4/4"` |
| 6 | `ifdescr` | `RC-INTF` | `interface[].description` | Port description string; may be empty |
| 7 | `iftype` | N/A | N/A | Fixed `"ethernetCsmacd"` for all uplink ports |
| 8 | `ifspeed` | `RC-INTF` | `interface[].speed` | Speed in bps; e.g., `10000000000` |
| 9 | `ifadmin` | `RC-INTF` | `interface[].admin-status` | `"up"` / `"down"` |
| 10 | `ifoper` | `RC-INTF` | `interface[].oper-status` | `"up"` / `"down"` |
| 11 | `ifindex` | `RC-INTF` | `interface[].if-index` | Integer as string |
| 12 | `ifphyaddr` | `RC-INTF` | `interface[].phys-address` | MAC address string |
| 13 | `ifalias` | `RC-INTF` | `interface[].description` | Same source as `ifdescr` |
| 14 | `moduleclass` | `UPLINK-SFP` | `eqpt:output.inventory[port-name==ifname].module-class` | e.g., `"10GBASE-ZR/ZW"` — join by port name |
| 15 | `vendorpn` | `UPLINK-SFP` | `eqpt:output.inventory[port-name==ifname].part-number` | e.g., `"SPP10EZRIDFEAL"` — join by port name |
| 16 | `mediatype` | `UPLINK-SFP` | `eqpt:output.inventory[port-name==ifname].fiber-type` | Map: `"single-mode"`→`"SM"`, `"multi-mode"`→`"MM"` |
| 17 | `altname` | N/A | N/A | Set same as `ifname`; or null |
| 18 | `name` | N/A | N/A | Compose: `"{device_name}:{ifname}"` |
| 19 | `ifconn` | `RC-INTF` | `interface[].oper-status` | `1` if `"up"`, else `0` |
| 20 | `dstport` | N/A | N/A | N/A — neighbor port; requires LLDP or manual mapping |
| 21 | `dstsite` | N/A | N/A | N/A — neighbor site; manual mapping |
| 22 | `dsttype` | N/A | N/A | N/A — neighbor device type; manual mapping |
| 23 | `dstname` | N/A | N/A | N/A — neighbor device name; LLDP or manual mapping |
| 24 | `dstsite2` | N/A | N/A | N/A — secondary neighbor site; manual mapping |
| 25 | `dsttype2` | N/A | N/A | N/A — secondary neighbor device type; manual mapping |
| 26 | `remdstsite` | N/A | N/A | N/A — remote destination site; manual mapping |
| 27 | `sys_pollstatus` | N/A | N/A | Default `1` |
| 28 | `usr_pollstatus` | N/A | N/A | Default `1` |
| 29 | `first` | N/A | N/A | Set to `NOW()` on first insert only |
| 30 | `lastseen` | N/A | N/A | Set to `NOW()` on every discovery run |
| 31 | `last_modify_at` | N/A | N/A | Set to `NOW()` on every update |
| 32 | `last_modify_by` | N/A | N/A | Fixed `"nokia-discovery"` |

---

### `ponport` — All Fields

> Scope: one row per fiber intent (one fiber = one PON port on one LT card)

| # | db_colname | api_endpoint | api_field | processing_logic |
|---|---|---|---|---|
| 1 | `id` | `RC-INTF-ONE` | `ietf-interfaces:interface.if-index` | Compose: `"{device.id}.{ifindex}"` |
| 2 | `device_id` | N/A | N/A | FK from `device.id` matched by OLT name |
| 3 | `device_ip` | N/A | N/A | From `device.ip` |
| 4 | `device_name` | N/A | N/A | From `device.name` |
| 5 | `ifname` | `ES-FIBER` | `hits._source.target.fiber-name` | e.g., `"SWOLT000044.L1P1"` |
| 6 | `ifdescr` | `ES-FIBER` | `hits._source.target.fiber-name` | Same as `ifname`; or RC-Proxy description if available |
| 7 | `iftype` | `ES-FIBER` | `hits._source.configuration.xpon-type[0]` | `"gpon"` → `"gpon"` ; `"xgs-pon"` / `"mpm-gpon-xgs"` → `"xgs-pon"` |
| 8 | `ifspeed` | `ES-FIBER` | `hits._source.configuration.xpon-type[0]` | GPON: `2488000000`, XGS-PON: `10000000000` (bps) |
| 9 | `ifadmin` | `RC-INTF-ONE` | `ietf-interfaces:interface.admin-status` | `"up"` / `"down"` |
| 10 | `ifoper` | `RC-INTF-ONE` | `ietf-interfaces:interface.oper-status` | `"up"` / `"down"` |
| 11 | `ifindex` | `RC-INTF-ONE` | `ietf-interfaces:interface.if-index` | Integer as string |
| 12 | `ifphyaddr` | N/A | N/A | N/A — PON ports have no MAC address; set null |
| 13 | `ifalias` | N/A | N/A | N/A — set same as `ifname` or null |
| 14 | `ponport` | `ES-FIBER` | `hits._source.target.fiber-name` | Parse fiber name: `SWOLT000044.L{lt}P{port}` → `"1-1-{lt}-{port}"` |
| 15 | `moduleclass` | `PON-SFP` | `pon-sfp:output.pon-optics[].wavelength` | 1490nm present → `"GPON CLASS B+"` ; 1577nm → `"XGS-PON"` ; both → `"GPON/XGS-PON"` |
| 16 | `vendorpn` | `PON-SFP` | `pon-sfp:output.inventory.part-number` | e.g., `"3FE47581BF"` |
| 17 | `l1_dl_max_bw` | `ES-FIBER` | `hits._source.configuration.xpon-type[0]` | GPON: `2488`, XGS-PON: `10240` (Mbps) |
| 18 | `l1_ul_max_bw` | `ES-FIBER` | `hits._source.configuration.xpon-type[0]` | GPON: `1244`, XGS-PON: `10240` (Mbps) |
| 19 | `l1sp` | `ES-FIBER` | `hits._source.configuration.port-profile[0]` | e.g., `"Default Port Profile"` |
| 20 | `ifconn` | `ES-ONT` | `hits.total.value` | Count ONT intents where `configuration.fiber-name == {{fiber-name}}` |
| 21 | `dl_bw_remaining` | N/A | N/A | Optional — enable §4.2.15, then query OpenTSDB PON utilization |
| 22 | `ul_bw_remaining` | N/A | N/A | Optional — enable §4.2.15, then query OpenTSDB PON utilization |
| 23 | `name` | N/A | N/A | Compose: `"{device_name}:{ponport}"` e.g., `"SWOLT000044:1-1-1-1"` |
| 24 | `sys_pollstatus` | N/A | N/A | Default `1` |
| 25 | `usr_pollstatus` | N/A | N/A | Default `1` |
| 26 | `first` | N/A | N/A | Set to `NOW()` on first insert only |
| 27 | `lastseen` | N/A | N/A | Set to `NOW()` on every discovery run |
| 28 | `last_modify_at` | N/A | N/A | Set to `NOW()` on every update |
| 29 | `last_modify_by` | N/A | N/A | Fixed `"nokia-discovery"` |
