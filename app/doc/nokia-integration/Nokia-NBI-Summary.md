# Nokia Altiplano NBI Integration — Document Summary

> Generated: 2026-06-01  
> Source documents in this folder

---

## Overall Integration Architecture

```
TRUE OSS/SMP
    │
    ├── REST (JWT auth) ──────→ Altiplano AC (IBN Actions / T&D)
    ├── RESTCONF GET ──────────→ Altiplano RC-Proxy (device-level queries)
    ├── Kafka subscribe ───────→ Altiplano Kafka (PM metrics, alarms, inventory changes)
    ├── REST GET ──────────────→ OpenTSDB (bulk PM counter history, 7-day retention)
    └── REST GET ──────────────→ Elasticsearch (inventory: ONT, hardware, intent state)
                                        │
                                  Nokia Altiplano
                                        │
                                  NETCONF / IPFIX
                                        │
                             Lightspan XGS-PON OLTs
                                        │
                                  ONTs (subscribers)
```

**Hardware supported:**
- **Lightspan MF-2** — Dual control cards, PON cards (LT1/LT2), iHub, uplink 1/10GE
- **Lightspan DF-16GM (CFXR-H shelf)** — 16 MultiPON ports, 100GE uplink

---

## Document 1: TRUE FTTH Network (XGSPON) — NBI Integration Guide v0.1

**File:** `TRUE FTTH Network (XGSPON)_NBI Integration Guide_v0.1.docx`  
**Author:** Nokia (Ronghuan Tu) | **Date:** 2024-03-13 | **Edition:** 0.1

### Authentication

| Endpoint | Method | Purpose |
|---|---|---|
| `/altiplano-sso/realms/master/protocol/openid-connect/token` | POST | JWT token for intent/ES APIs (expires 1800s, refresh 86400s) |
| Separate endpoint | — | T&D query authentication |

Headers: `Authorization: Basic <base64>` → Response: `{ "access_token": "...", "token_type": "Bearer" }`

---

### 4.2 Test & Diagnosis — IBN ACTION (POST to Altiplano AC)

Base URL: `{{releasename}}-altiplano-ac/rest/restconf/data/ibn:ibn/intent=`

| # | Function | Key Output Fields |
|---|---|---|
| 1 | Get MAC address for CFM | `mac-address` |
| 2 | Maintenance Association | MD profile, MA/MEP config |
| 3 | Get ONT Detail Information | `oper-status`, `admin-status`, `detected-serial-number`, `active-sw-version`, `rx-power-dbm-at-olt`, `onu-fiber-distance`, FEC counters |
| 4 | Get UNI Detail Information | `oper-status`, `speed`, `duplex`, `in-octets`, `out-octets` |
| 5 | Reboot ONT | HTTP 204 No Content |
| 6 | Lock UNI | HTTP 204 No Content |
| 7 | Unlock UNI | HTTP 204 No Content |
| 8 | Show Fiber SFP Inventory | wavelength, `tx-power`, `tx-bias-current`, `module-temperature`, serial-number, part-number |
| 9 | Show Fiber Optics Measurement | Per-ONT: `tx-power`, `rx-power`, `rx-power-olt`, `fiber-distance` |
| 10 | Get VLAN Sub-Interface Info | `vlan-id` on service interface |
| 11 | Query VLAN Association DHCP Sessions | DHCP lease IP, expiry, MAC (`chaddr`) |
| 12 | Query All MF OLT | List all OLTs |
| 13 | Query All Fiber under OLT | List all PON ports on an OLT |
| 14 | Show Equipment Slot Inventory | Line card / chassis inventory |
| 15 | Enable/Disable PON Utilization Monitoring | Toggle PON utilization |
| 16 | Show FDB MAC Address | Forwarding database lookups |
| 17 | Show Uplink Port SFP Diagnostics | Uplink SFP optical diagnostics |
| 18 | Restart | Card restart |
| 19 | Show Last Restart Time of Slot | Last restart timestamp |
| 20 | Show NT Protection State | NT A/B protection status |
| 21 | Show Forwarding Database MAC | MAC table query |
| 22 | Show CFM MAC Per Board | `service-id`, `port`, `onu-name`, `mac` |
| 23 | Show Optics Inventory Information | Per-ONT optics inventory |
| 24 | Show LAG Statistics | Link Aggregation Group stats |

**ONT Name pattern:** `{{OLTName}},ont`  
**Fiber Name pattern:** `SWOLTxxxxxx.Lyy.Pzz` (e.g. `SWOLT0000333.L13.P05`)

---

### 4.3 RC-Proxy Queries (RESTCONF GET)

Base URL: `{{releasename}}-altiplano-rcdeviceproxy/rest/restconf/data/anv:device-manager/anv-device-holders:device={{LT Device Name}}/device-specific-data/`

| Query | YANG Path | Key Fields |
|---|---|---|
| ONT Admin/Oper Status | `ietf-interfaces:interfaces-state/interface={{ONT Name}}` | `admin-status`, `oper-status`, `last-change` |
| ONT Software Version | `ietf-hardware:hardware-state/component/...` | `active-sw-version`, `passive-sw-version` |
| ONT Optical Power | `ietf-hardware:hardware-state/component={{PON}}_[GPON\|XGS]/transceiver-link` | `tx-power-dbm`, `rx-power-dbm`, `rssi-onu` |
| ONT Eth Port State | `ietf-interfaces:interfaces-state/interface=VENET_{{ONT}}_{{UNI}}` | `oper-status`, `speed`, `auto-negotiation` |
| NTD UNI-D Counters | `.../interface=VENET_{{ONT}}_{{UNI}}/statistics` | `in-octets`, `out-octets`, `in-discards`, `out-discards` |
| VLAN Association Counters | `.../interface=VSI_{{ONT}}_{{LAN}}_{{Service}}/statistics` | in/out octets, DHCPv4/v6 relay stats, PPPoE IA stats |
| Bridge Port VLAN | `.../interface=VSI_{{ONT}}_{{LAN}}_{{Service}}/bbf-frame-processing-profile:tag-0` | `vlan-id` |
| PON Admin/Oper Status | `.../interface={{Fiber Name}}` | `admin-status`, `oper-status`, channel allocation |
| PON Optical Data | `ietf-hardware:hardware-state/component={{PON_ID}}_[GPON\|XGS]/transceiver-link` | `tx-power-dbm`, `rx-power-dbm` per ONT |
| DHCP Session Info | `.../interface=VSI_{{ONT}}_{{LAN}}_{{Service}}_{{AVC ID}}/ipv4-security` | `ip`, `lease-time`, `ip-address-expiry-time`, `chaddr` |

---

### 4.4 PM Interface

#### Collection Modes

| Mode | Mechanism | Use Case |
|---|---|---|
| **Bulk (primary)** | IPFIX inside OLT → Altiplano OpenTSDB | Every 5/15 min, network-wide |
| **Live (ad-hoc)** | RESTCONF GET from Altiplano to device | Troubleshooting only |
| **Kafka streaming** | OSS subscribes to Kafka topics | Near-real-time metrics |

#### Counters Collected

| Point | Interval | Counters |
|---|---|---|
| Uplink | 15 min | Out Octets, Out Packets, Out Drop Packets |
| PON | 5 min | TX/RX utilization, TX/RX total bytes, TX/RX total packets |

#### OpenTSDB Query API

```
GET /altiplano-opentsdb/api/suggest?type=metrics&max=50000   # list all metrics
GET /altiplano-opentsdb/api/query?start=24h-ago&m=sum:<metric>.<device>.<card>
```

Key metric names:
- CPU idle: `bbf-hardware-cpu-resource__c_cpu-processor-data/percent-cpu-usage/percent-cpu-idle`
- Free memory: `bbf-hardware-cpu-resource__c_cpu-processor-data/memory-usage/free-memory`
- Tx power dBm: `bbf-hardware-transceivers__c_transceiver-link/diagnostics/nokia-hardware-transceivers-dbm__c_tx-power-dbm`
- Rx power dBm: `bbf-hardware-transceivers__c_transceiver-link/diagnostics/nokia-hardware-transceivers-dbm__c_rx-power-dbm`
- PON traffic: `statistics/out-octets.<OLT>.<LT>`, `statistics/out-packets.<OLT>.<LT>`

#### Kafka PM Sample Output Fields (PON Traffic)

```json
{
  "name": "CT_QCENGMF2-1-9_9_GPON",
  "statistics": {
    "out-octets": "41253252458",
    "in-octets": "828635229",
    "out-discards": 26837,
    "in-discards": 399,
    "bbf-interfaces-statistics-management:in-pkts": "3782806",
    "bbf-interfaces-statistics-management:out-pkts": "28368388",
    "nokia-sdan-additional-statistics:in-dropped-bytes": "44694",
    "nokia-sdan-additional-statistics:out-dropped-bytes": "39700406",
    "nokia-sdan-xpon-statistics:xpon": {
      "out-unicast-gem-port-bytes": "...",
      "out-unicast-gem-port-packets": "...",
      "out-multicast-gem-port-bytes": "..."
    }
  }
}
```

---

### 4.5 Inventory Interface (Elasticsearch)

#### Intent Inventory
```
GET {{server}}/altiplano-indexsearch/intents/_search/
```
Fields: `pon-type`, `expected-loid`, `uni-id`, `detected-serial-number`, `active-sw-version`

#### Device Inventory
```
GET {{server}}/altiplano-elasticsearch/latestcompleted-inv/_search
```

Query by `inventorydata.ietf-hardware:hardware.component.class.keyword`:

| Class | Description |
|---|---|
| `iana-hardware:chassis` | OLT chassis |
| `nokia-hardware-identities:slot-nt` | NT cards (A/B) |
| `nokia-hardware-identities:slot-lt` | Line terminal cards |

---

## Document 2: Phase2-Summary-KPIs-Nokia-r2.xlsx

**File:** `Phase2-Summary-KPIs-Nokia-r2.xlsx`

KPI mapping defining what to collect and how, across 5 sheets:

### OLT Uplink KPIs (SNMP)

| KPI | SNMP OID |
|---|---|
| Bias Current | `1.3.6.1.4.1.637.61.1.56.5.1.6.4353` |
| Voltage | `1.3.6.1.4.1.637.61.1.56.5.1.7.4353` |
| Tx Power | `1.3.6.1.4.1.637.61.1.56.5.1.8.4353` |
| Rx Power | `1.3.6.1.4.1.637.61.1.56.5.1.9.4353` |
| Temperature | `1.3.6.1.4.1.637.61.1.56.5.1.10.4353` |

### OLT PON KPIs (SNMP)

| KPI | Notes |
|---|---|
| Rx/Tx CRC Error | |
| Rx/Tx BIP Error | |
| Tx/Rx Packets | Bytes: `1.3.6.1.4.1.637.61.1.35.21.45.1.11`, `...45.1.12` |
| Voltage, SFP Temperature | |
| Tx/Rx Power (Dual Channel) | GPON 1490nm/1310nm, XGS-PON 1577nm/1270nm |
| Tx/Rx Power (Single Channel) | |
| Bias Current (Dual/Single) | |

### ONU PON KPIs (Altiplano NBI)

| KPI | Collection Method |
|---|---|
| Tx Power | Altiplano NBI |
| Rx Power | Altiplano NBI |
| Bias Current | Altiplano NBI |
| Voltage | Altiplano NBI |
| Temperature | Altiplano NBI |
| Oper Status | Altiplano NBI |
| Serial Number | Altiplano NBI |
| Last Down Time | Altiplano NBI |
| Last Down Cause | Altiplano NBI |

### PON Traffic KPIs (Altiplano NBI Bulk)

| KPI | Field Name |
|---|---|
| In/Out Unicast Packets | `in_ucast_pkt`, `out_ucast_pkt` |
| In/Out Broadcast Packets | `in_bcast_pkt`, `out_bcast_pkt` |
| In/Out Multicast Packets | `in_mcast_pkt`, `out_mcast_pkt` |
| In/Out Octets | `in_octets`, `out_octets` |
| In/Out Total Packets | `in_pkt`, `out_pkt` |
| In Errors (CRC) | `in_err` |

---

## Document 3: True_Altiplano NBI Integration for PM and Inventory (PDF)

**File:** `True_Altiplano NBI Integration for PM and Inventory_20250421.pdf`  
**Date:** April 2025 | **Type:** Presentation / slide deck

### Key Concepts

**IBN (Intent-Based Networking):** Altiplano separates "what" (intent) from "how" (device config). OSS specifies high-level intent; Altiplano translates to NETCONF/YANG device operations.

**Kafka as message bus:** OSS subscribes to Kafka topics for:
- Alarms and notifications
- Performance measurements / telemetry streaming
- NE notifications
- Intent health changes
- Device metrics

**OpenTSDB:** Stores bulk PM counters with 7-day retention. Supports downsampling (avg, min, max) and aggregation across tags (avg, min, max, p90).

### ONT Inventory Fields → API Mapping

| Field | API Endpoint |
|---|---|
| Model Name | `ont-show-detail` (Section 4.2.3) |
| Oper Status | `ont-show-detail` (Section 4.2.3) |
| Serial Number | `ont-show-detail` (Section 4.2.3) |
| MAC Address | `show-cfm-mac-per-board` (Section 4.2.22) |
| LOID | Intent inventory Elasticsearch (Section 4.5.2.5) |
| Fiber Distance | `show-optical-measurements` (Section 4.2.9) |
| Rx Power (dBm) | `ont-show-detail` (Section 4.2.3) |

### Two PM Collection Methods

```
Method 1: Kafka consumer
  OSS ──subscribe──→ Kafka topic ──→ real-time metric stream

Method 2: OpenTSDB REST query
  OSS ──GET──→ /altiplano-opentsdb/api/query?start=24h-ago&m=sum:<metric>.<device>.<card>
```
