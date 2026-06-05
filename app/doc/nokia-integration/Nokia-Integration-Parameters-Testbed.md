# Nokia Altiplano NBI — Integration Parameters (Testbed)

> Source: E2E_test_report_v2_22012025.xlsx  
> Environment: **Testbed / Development**  
> Updated: 2026-06-05

---

## 1. General Environment

| Parameter | Value |
|---|---|
| Server hostname / IP | `10.50.238.203` |
| Port | `443` |
| Protocol | `https` |
| Release name prefix | `nokia-altiplano` |

---

## 2. AUTH — Altiplano SSO

> Nokia uses a built-in REST auth endpoint (not Keycloak/OpenID Connect).

| Parameter | Value |
|---|---|
| Token endpoint URL | `https://10.50.238.203/nokia-altiplano-ac/rest/auth/login` |
| Refresh token URL | `https://10.50.238.203/nokia-altiplano-ac/rest/auth/refreshAccessToken` |
| Auth method (login) | Basic Auth (username + password) |
| Username | `adminuser` |
| Password | `password` |
| Token expiry | `1800 s` (30 min) |
| Token type | JWT Bearer |
| Response fields | `accessToken`, `refreshToken` |

### Postman Post-response Script
```javascript
pm.environment.set("access-token", pm.response.json().accessToken);
pm.environment.set("refresh-token", pm.response.json().refreshToken);
```

---

## 3. AUTH (T&D) — RC-Proxy Authentication

> Same server and credentials as SSO above.

| Parameter | Value |
|---|---|
| Auth endpoint URL | `https://10.50.238.203/nokia-altiplano-ac/rest/auth/login` |
| Auth method | Bearer Token (JWT from AC login endpoint) |
| Username | `adminuser` |
| Password | `password` |
| Token header | `Authorization: Bearer {access-token}` |
| Token expiry / refresh | `1800s`; refresh via `/rest/auth/refreshAccessToken` |
| Same server as SSO | Yes (`10.50.238.203`) |

---

## 4. AC — Analytics Controller

| Parameter | Value |
|---|---|
| Server hostname / IP | `10.50.238.203` |
| Port | `443` |
| Release name (`<rel>`) | `nokia-altiplano` |
| Full base URL | `https://10.50.238.203/nokia-altiplano-ac/rest/restconf/data/` |
| Auth | Bearer Token (`Authorization: Bearer {access-token}`) |
| Content-Type | `application/yang-data+json` |
| Accept | `application/yang-data+json` |

### Example endpoints
| Description | Method | Path |
|---|---|---|
| ONT info & status | POST | `.../ibn:ibn/intent=<NE>-<LT>-<PON>-<ONT>,ont/intent-specific-data/ont-action:show-ont-info` |
| ONT config (type, profile) | GET | `.../ibn:ibn/intent=<NE>-<LT>-<PON>-<ONT>,ont/intent-specific-data/ont:ont` |
| PON optical measurements | POST | `.../ibn:ibn/intent=<NE>-<LT>-<PON>,fiber/intent-specific-data/optics:show-optical-measurements` |
| PON SFP type | GET | `.../ibn:ibn/intent=<NE>-<LT>-<PON>,fiber/intent-specific-data/fiber:fiber` |
| Uplink SFP type | GET | `.../ibn:ibn/intent=<NE>,uplink-connection/intent-specific-data/uplink-connection:uplink-connection` |

---

## 5. RC-Proxy — RC Device Proxy

| Parameter | Value |
|---|---|
| Server hostname / IP | `10.50.238.203` |
| Port | `443` |

---

## 6. ES — Elasticsearch

| Parameter | Value |
|---|---|
| Server hostname / IP | `10.50.238.203` |
| Port | `443` |
| Base URL | `https://10.50.238.203/altiplano-indexsearch/` |
| Search endpoint | `https://10.50.238.203/altiplano-indexsearch/intents/_search/` |
| Auth | Bearer Token (same JWT as AC) |
| Content-Type | `application/json` |
| Accept | `application/json` |

### Example query (bandwidth profile by ONT)
```json
POST /altiplano-indexsearch/intents/_search/

{
  "from": "0",
  "size": "9999",
  "query": {
    "bool": {
      "filter": [
        { "term": { "intent-type": "l2-user" } },
        { "term": { "configuration.user-device-name.keyword": "QCENGDF16GM-1-7-1" } }
      ]
    }
  },
  "_source": ["target.l2-user-name", "configuration"]
}
```

---

## 7. Kafka — Broker Connection

| Parameter | Value |
|---|---|
| Bootstrap server | `10.50.238.203` |
| Port | `9093` (SSL) |
| Security protocol | `SSL` |
| Authentication method | `mTLS` |
| CA certificate | `av-kafka-client-trustchain-cert.pem` |
| Client certificate | `av-kafka-client-cert.pem` |
| Client key | `av-kafka-client-key.pem` |

### kcat test command
```bash
kcat -C -b 10.50.238.203:9093 \
  -X security.protocol=SSL \
  -X ssl.key.location=/tmp/kafka_certs/av-kafka-client-key.pem \
  -X ssl.certificate.location=/tmp/kafka_certs/av-kafka-client-cert.pem \
  -X ssl.ca.location=/tmp/kafka_certs/av-kafka-client-trustchain-cert.pem \
  -X ssl.key.password="[HIDDEN]" \
  -t IPFIX-XPON -o beginning -c 5
```

---

## 8. Kafka — Topics & Message Format

| Parameter | Value |
|---|---|
| Topic — uplink interface traffic | `IPFIX-XPON` |
| Topic — uplink SFP optical | `IPFIX-XPON` |
| Topic — PON SFP optical | `IPFIX-XPON` |
| Topic — PON interface traffic | `IPFIX-XPON` |
| Message format | `JSON` |

---

## 9. Postman Environment Variables (E2E_Rest_intent_Action)

| Variable | Initial Value | Notes |
|---|---|---|
| `server` | `10.50.238.203` | |
| `user name` | `adminuser` | |
| `password` | `password` | |
| `protocol` | `https` | |
| `servicename` | `altiplano-av` | |
| `base-url` | `nokia-altiplano-ac` | Used in AC endpoints |
| `access-token` | *(set by login script)* | JWT, expires 30 min |
| `refresh-token` | *(set by login script)* | Used to renew access-token |

---

## 10. Test NE Reference

| NE | Slot (LT) | PON | ONT |
|---|---|---|---|
| `QCENGDF16GM` | 1 | 7 | 1–5 |
| `QCENGMF2` | 1 | 4 | 1 |

Format: `<NeName>-<LT>-<PON>-<ONT>` (e.g., `QCENGDF16GM-1-7-1`)
