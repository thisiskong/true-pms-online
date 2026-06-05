# Nokia Altiplano NBI — Integration Prerequisites

**Purpose:** Checklist of all information required from Nokia/system owners before development can begin.  
**Project:** Nokia Altiplano NBI Integration — Device, Uplink Interface & PON Port Discovery  
**Date:** 2026-06-01

---

## Summary of Backends

| # | Backend | Protocol | Role |
|---|---|---|---|
| 1 | **AUTH** — Altiplano SSO | HTTPS / OAuth2 OpenID Connect | Issues JWT token for ES and AC backends |
| 2 | **AUTH (T&D)** — T&D Auth | HTTPS / TBD | Issues credential for RC-Proxy backend |
| 3 | **ES** — Elasticsearch | HTTPS / REST | Query OLT, fiber, ONT intent index |
| 4 | **AC** — Analytics Controller | HTTPS / RESTCONF | Intent-level IBN actions (slot inventory, SFP info) |
| 5 | **RC-Proxy** — RC Device Proxy | HTTPS / RESTCONF | Live device state via NETCONF proxy |

---

## Information Request Checklist

### 1. AUTH — Altiplano SSO

Used by: **ES** and **AC** backends

| # | Item | Example / Format | Status |
|---|---|---|---|
| 1 | Server hostname or IP | `altiplano.example.com` or `10.x.x.x` | ⬜ |
| 2 | Port | `443` (HTTPS) or custom | ⬜ |
| 3 | Protocol | `HTTPS` | ⬜ |
| 4 | Full token endpoint URL | `https://<server>/altiplano-sso/realms/master/protocol/openid-connect/token` | ⬜ |
| 5 | Username | `adminuser` | ⬜ |
| 6 | Password | `*****` | ⬜ |
| 7 | Token expiry | `1800` seconds (default) | ⬜ |
| 8 | SSL/TLS certificate | Self-signed? CA cert required? | ⬜ |
| 9 | Realm name | `master` (default) or custom | ⬜ |

**Request body format (confirmed from doc):**
```http
POST /altiplano-sso/realms/master/protocol/openid-connect/token
Authorization: Basic <base64(username:password)>
```

---

### 2. AUTH (T&D) — RC-Proxy Authentication

Used by: **RC-Proxy** backend only

> ⚠️ The NBI Integration Guide (§4.1) states a **separate authentication endpoint** exists for T&D/RC-Proxy queries. Details are not documented. Must confirm with Nokia.

| # | Item | Example / Format | Status |
|---|---|---|---|
| 1 | Auth endpoint URL | TBD | ⬜ |
| 2 | Auth method | Basic / Bearer / Certificate / Other? | ⬜ |
| 3 | Username | TBD | ⬜ |
| 4 | Password | TBD | ⬜ |
| 5 | Token format / header name | `Authorization: Bearer ...` or other? | ⬜ |
| 6 | Token expiry / refresh mechanism | TBD | ⬜ |
| 7 | Is it the same server as AUTH SSO? | Yes / No | ⬜ |

---

### 3. ES — Elasticsearch

Used for: OLT list, fiber (PON port) list, ONT count per fiber

| # | Item | Example / Format | Status |
|---|---|---|---|
| 1 | Server hostname or IP | Same as Altiplano server or separate? | ⬜ |
| 2 | Port | `443` or `9200` or custom | ⬜ |
| 3 | Protocol | `HTTPS` | ⬜ |
| 4 | Base URL | `https://<server>/altiplano-elasticsearch/` | ⬜ |
| 5 | Index name — intent | `intents/_search/` (confirmed from doc) | ✅ |
| 6 | Index name — inventory | `latestcompleted-inv/_search` (confirmed from doc) | ✅ |
| 7 | Auth | JWT Bearer token from AUTH SSO (confirmed from doc) | ✅ |
| 8 | ES version | 7.x / 8.x? (affects query DSL compatibility) | ⬜ |
| 9 | SSL/TLS certificate | Same CA as SSO server? | ⬜ |
| 10 | Max results per page (`size`) | Default `10`; confirm max allowed | ⬜ |
| 11 | Network accessibility | Reachable from OSS server directly? VPN required? | ⬜ |

---

### 4. AC — Analytics Controller

Used for: slot inventory, uplink SFP info, PON SFP info

| # | Item | Example / Format | Status |
|---|---|---|---|
| 1 | Server hostname or IP | Same as Altiplano server or separate? | ⬜ |
| 2 | Port | `443` or custom | ⬜ |
| 3 | Protocol | `HTTPS` | ⬜ |
| 4 | Release name (`<rel>`) | Used in URL prefix e.g., `nokia-altiplano-ac` | ⬜ |
| 5 | Full base URL | `https://<server>/<rel>-altiplano-ac/rest/restconf/data/` | ⬜ |
| 6 | Auth | JWT Bearer token from AUTH SSO (confirmed from doc) | ✅ |
| 7 | SSL/TLS certificate | Self-signed? CA cert required? | ⬜ |
| 8 | Network accessibility | Reachable from OSS server directly? VPN required? | ⬜ |
| 9 | Rate limiting | Max requests/sec? Throttling policy? | ⬜ |
| 10 | Altiplano version | `22.9` / `22.12` / other (affects YANG model) | ⬜ |

---

### 5. RC-Proxy — RC Device Proxy

Used for: live interface state (uplink admin/oper status, speed), PON port admin/oper status

| # | Item | Example / Format | Status |
|---|---|---|---|
| 1 | Server hostname or IP | Same as Altiplano server or separate? | ⬜ |
| 2 | Port | `443` or custom | ⬜ |
| 3 | Protocol | `HTTPS` | ⬜ |
| 4 | Release name (`<rel>`) | Used in URL prefix e.g., `nokia-altiplano-rcdeviceproxy` | ⬜ |
| 5 | Full base URL | `https://<server>/<rel>-altiplano-rcdeviceproxy/rest/restconf/data/` | ⬜ |
| 6 | Auth method | Separate T&D auth (§4.1) — details TBD | ⬜ |
| 7 | SSL/TLS certificate | Self-signed? CA cert required? | ⬜ |
| 8 | Network accessibility | Reachable from OSS server directly? VPN required? | ⬜ |
| 9 | Rate limiting | Max requests/sec? Throttling policy? | ⬜ |
| 10 | LT device name format | `SWOLT000044.LT1` (confirmed from doc) | ✅ |

---

## General / Common Information Needed

| # | Item | Notes | Status |
|---|---|---|---|
| 1 | Are all 5 backends on the same server/IP? | May share one host or be split | ⬜ |
| 2 | Firewall rules | OSS server IP must be whitelisted | ⬜ |
| 3 | VPN / network path required? | Site-to-site VPN or direct? | ⬜ |
| 4 | SSL certificate (CA bundle) | For HTTPS verification; provide `.pem` or `.crt` | ⬜ |
| 5 | Altiplano release/version | e.g., `22.12` — affects URL prefix and YANG model | ⬜ |
| 6 | Environment type | Production / Pre-production / Lab | ⬜ |
| 7 | Contact person (Nokia) | Name, email for technical queries | ⬜ |
| 8 | Read-only account confirmed? | Ensure discovery credentials have read-only scope | ⬜ |
| 9 | Number of OLTs in scope | Needed to estimate API call volume per discovery run | ⬜ |
| 10 | Scheduled maintenance windows | To avoid discovery collisions | ⬜ |

---

## Questions to Confirm with Nokia

1. Are the Altiplano server hostname/IP and port the same for ES, AC, and RC-Proxy, or are they on separate hosts?
2. What is the `<releasename>` prefix used in AC and RC-Proxy URLs for this environment?
3. What is the exact auth endpoint and method for RC-Proxy (T&D auth)?
4. Is a CA certificate required for TLS verification, or is the server using a public CA?
5. Are there any API rate limits or throttling policies we should design around?
6. What Altiplano software version is running? (affects YANG model compatibility)
7. Can the discovery service account be scoped to read-only access only?
8. Is the Altiplano instance reachable directly from our OSS network, or is a VPN/jump host required?

---

## Kafka Integration Kickstart Checklist

### A. Kafka Broker Connection

| # | Item | Example / Format | Status |
|---|---|---|---|
| 1 | Bootstrap server(s) | `kafka1.example.com:9092,kafka2.example.com:9092` | ⬜ |
| 2 | Port | `9092` (plain) / `9093` (SSL) | ⬜ |
| 3 | Protocol | `PLAINTEXT` / `SSL` / `SASL_PLAINTEXT` / `SASL_SSL` | ⬜ |
| 4 | Authentication method | `SASL/PLAIN` / `SASL/SCRAM-SHA-256` / `mTLS` / None | ⬜ |
| 5 | SASL username | TBD | ⬜ |
| 6 | SASL password | TBD | ⬜ |
| 7 | SSL/TLS CA certificate | `.pem` / `.crt` file | ⬜ |
| 8 | Client certificate (if mTLS) | `.crt` + `.key` files | ⬜ |
| 9 | Network accessibility | Reachable from OSS server? VPN required? | ⬜ |
| 10 | Firewall whitelist | OSS server IP must be allowed | ⬜ |

### B. Kafka Topics

| # | Item | Notes | Status |
|---|---|---|---|
| 1 | Topic — uplink interface traffic | e.g., `altiplano.pm.uplink.traffic` | ⬜ |
| 2 | Topic — uplink SFP optical | e.g., `altiplano.pm.uplink.sfp` | ⬜ |
| 3 | Topic — PON SFP optical | e.g., `altiplano.pm.pon.sfp` | ⬜ |
| 4 | Topic — PON interface traffic | e.g., `altiplano.pm.pon.traffic` | ⬜ |
| 5 | Are all PM metrics in one topic or separate? | Confirm with Nokia | ⬜ |
| 6 | Topic retention period | e.g., `7 days` | ⬜ |
| 7 | Number of partitions per topic | Affects consumer parallelism | ⬜ |
| 8 | Message format | `JSON` / `Avro` / `Protobuf` | ⬜ |
| 9 | Message compression | `none` / `gzip` / `snappy` / `lz4` | ⬜ |
| 10 | Avro schema registry URL | If Avro format is used | ⬜ |

### C. Consumer Configuration

| # | Item | Recommended Value | Status |
|---|---|---|---|
| 1 | Consumer group ID | `pms-nokia-collector` | ⬜ |
| 2 | Auto offset reset | `earliest` (to not miss data on restart) | ⬜ |
| 3 | Enable auto commit | `false` (manual commit after DB write) | ⬜ |
| 4 | Max poll records | `500` | ⬜ |
| 5 | Session timeout | `30000` ms | ⬜ |
| 6 | Heartbeat interval | `10000` ms | ⬜ |

### D. Nokia-side Configuration (Request from Nokia)

| # | Item | Notes | Status |
|---|---|---|---|
| 1 | IPFIX enabled on OLTs? | Must be pre-configured by Nokia | ⬜ |
| 2 | IPFIX push interval confirmed | 5 min (PON) / 15 min (uplink) | ⬜ |
| 3 | Which counters are included in push | Confirm against KPI list | ⬜ |
| 4 | PON utilization monitoring enabled | Required for BW remaining fields (§4.2.15) | ⬜ |
| 5 | Kafka topic names (official) | Get exact names from Nokia | ⬜ |
| 6 | Kafka schema documentation | YANG model / JSON schema for each topic | ⬜ |
| 7 | Sample Kafka messages | Request sample JSON per topic | ⬜ |
| 8 | Number of OLTs in scope | Estimate message volume | ⬜ |

### E. Development Prerequisites

| # | Item | Notes | Status |
|---|---|---|---|
| 1 | Nokia discovery integration complete | `device`, `intf`, `ponport` tables populated | ⬜ |
| 2 | Interface name → ifindex mapping table built | Required for Kafka → DB join | ⬜ |
| 3 | Counter state store designed | Redis / DB table for last-seen counter values | ⬜ |
| 4 | Daily aggregation job designed | 5-min → 1-day rollup logic | ⬜ |
| 5 | Kafka consumer library selected | e.g., `confluent-kafka-go`, `sarama`, `kafka-python` | ⬜ |
| 6 | Dead letter queue for parse errors | Handle malformed messages | ⬜ |
| 7 | Monitoring / alerting for lag | Alert if consumer falls behind | ⬜ |

---

## Status Legend

| Symbol | Meaning |
|---|---|
| ✅ | Confirmed from documentation |
| ⬜ | Not yet confirmed — need from Nokia/system owner |
