# Nokia Altiplano — PM Data Collection via Kafka

**Purpose:** Field mapping and implementation guide for integrating Nokia XGS-PON PM data into existing DB tables via Kafka streaming.  
**Source documents:** NBI Integration Guide v0.1, PM & Inventory PDF (Apr 2025), KPI Excel  
**Date:** 2026-06-01

---

## Overview

Nokia Altiplano collects PM counters from Lightspan OLTs via **IPFIX** and streams them through **Kafka** topics. OSS subscribes as a Kafka consumer and processes incoming messages to populate PM tables.

```
Lightspan OLT
    │ IPFIX (push every 5/15 min)
    ▼
Nokia Altiplano
    │ Kafka broker (stream)
    ▼
OSS Kafka Consumer
    │ parse + delta calculation
    ▼
DB Tables (traffic1d, olt_uplink1d, olt_pon_1d, pontraffic1d)
```

**Two PM collection methods available:**
- **Kafka (primary)** — OSS subscribes to topics; near-real-time streaming
- **OpenTSDB REST (fallback)** — OSS queries `GET /altiplano-opentsdb/api/query` for historical data (7-day retention)

---

## Collection Intervals

| Data Type | IPFIX Push Interval | Target DB Table |
|---|---|---|
| Uplink interface traffic | 15 min | `traffic1d` |
| Uplink SFP optical | 15 min | `olt_uplink1d` |
| PON SFP optical | 5 min | `olt_pon_1d` |
| PON interface traffic | 5 min | `pontraffic1d` |

---

## Kafka Message Structure

All Kafka messages follow this wrapper structure:

```json
{
  "anv:device-manager": {
    "anv-device-holders:device": [
      {
        "device-id": "QCENGMF2.LT1",
        "timestamp": "2025-03-27T14:01:49+0000",
        "device-specific-data": {
          // varies by topic/data type — see sections below
        }
      }
    ]
  }
}
```

**Key fields:**
- `device-id` — LT device name (e.g., `SWOLT000044.LT1`); OLT name = prefix before `.`
- `timestamp` — measurement timestamp (ISO 8601 with timezone)
- `device-specific-data` — payload varies by Kafka topic

---

## Table 1: `traffic1d` — Uplink Interface Traffic

**Kafka data path:** `device-specific-data.ietf-interfaces:interfaces-state.interface[]`  
**Filter:** interface `name` matches uplink pattern (`gei_`, `xgei-`, `ge-`, `xe-`, `100ge`)  
**Interval:** 15 min (`meas = 900`)

### Kafka Payload Sample
```json
{
  "ietf-interfaces:interfaces-state": {
    "interface": [
      {
        "name": "gei_1/3/1",
        "statistics": {
          "in-octets": "12345678900",
          "out-octets": "98765432100",
          "in-discards": 5,
          "out-discards": 2,
          "bbf-interfaces-statistics-management:in-pkts": "3782806",
          "bbf-interfaces-statistics-management:out-pkts": "28368388",
          "nokia-sdan-additional-statistics:in-dropped-bytes": "44694",
          "nokia-sdan-additional-statistics:out-dropped-bytes": "39700406"
        }
      }
    ]
  }
}
```

### Field Mapping

| # | db_colname | Source | Kafka / Logic |
|---|---|---|---|
| 1 | `tstamp` | Kafka message | `device[].timestamp` — truncate to day |
| 2 | `ip` | device table | Lookup by OLT name (prefix of `device-id` before `.`) |
| 3 | `ifindex` | intf table | Lookup `intf.ifindex` where `intf.ifname == interface[].name` |
| 4 | `ifspeed` | intf table | `intf.ifspeed` |
| 5 | `meas` | Fixed | `900` (15 min = 900 sec) |
| 6 | `cnt` | Calculated | Number of 15-min intervals aggregated to 1d |
| 7 | `device` | device table | `device.name` |
| 8 | `vendor` | device table | `device.vendor` |
| 9 | `model` | device table | `device.model` |
| 10 | `sitename` | device table | `device.sitename` |
| 11 | `province` | device table | `device.province` |
| 12 | `region` | device table | `device.region` |
| 13 | `network` | device table | `device.network` |
| 14 | `topology` | device table | `device.topology` |
| 15 | `rn` | device table | `device.rn` |
| 16 | `pn` | device table | `device.pn` |
| 17 | `dn` | device table | `device.dn` |
| 18 | `ifname` | Kafka | `interface[].name` |
| 19 | `ifalias` | intf table | `intf.ifalias` |
| 20 | `ifdescr` | intf table | `intf.ifdescr` |
| 21 | `iftype` | intf table | `intf.iftype` = `"ethernetCsmacd"` |
| 22 | `dstname` | intf table | `intf.dstname` |
| 23 | `dstport` | intf table | `intf.dstport` |
| 24 | `dstsite` | intf table | `intf.dstsite` |
| 25 | `dsttype` | intf table | `intf.dsttype` |
| 26 | `mediatype` | intf table | `intf.mediatype` |
| 27 | `ringid` | intf table | `intf.ringid` → from device |
| 28 | `ringtopo` | device table | `device.ringtopo` |
| 29 | `hop` | device table | `device.hop` |
| 30 | `ahomingid` | device table | `device.a_homing_id` |
| 31 | `ahomingsite` | device table | `device.a_homing_site` |
| 32 | `bhomingid` | device table | `device.b_homing_id` |
| 33 | `bhomingsite` | device table | `device.b_homing_site` |
| 34 | `chomingid` | device table | `device.c_homing_id` |
| 35 | `chomingsite` | device table | `device.c_homing_site` |
| 36 | `uplinkip1` | device table | `device.uplink_ip1` |
| 37 | `uplinksite1` | device table | `device.uplink_site1` |
| 38 | `uplinkmodel1` | device table | `device.uplink_model1` |
| 39 | `uplinkip2` | device table | `device.uplink_ip2` |
| 40 | `uplinksite2` | device table | `device.uplink_site2` |
| 41 | `uplinkmodel2` | device table | `device.uplink_model2` |
| 42 | `in_octets` | Kafka | `statistics.in-octets` — **delta** from previous reading |
| 43 | `out_octets` | Kafka | `statistics.out-octets` — **delta** from previous reading |
| 44 | `in_rate` | Calculated | `in_octets / meas` (bytes/sec) |
| 45 | `out_rate` | Calculated | `out_octets / meas` (bytes/sec) |
| 46 | `max_rate` | Calculated | `MAX(in_rate, out_rate)` |
| 47 | `in_bw` | Calculated | `in_rate * 8 / ifspeed * 100` (% utilization) |
| 48 | `out_bw` | Calculated | `out_rate * 8 / ifspeed * 100` (% utilization) |
| 49 | `max_bw` | Calculated | `MAX(in_bw, out_bw)` |
| 50 | `in_err` | Kafka | `statistics.in-discards` — **delta** |
| 51 | `in_0_50` | Calculated | Count of intervals where `in_bw < 50%` |
| 52 | `in_50_60` | Calculated | Count of intervals where `50% ≤ in_bw < 60%` |
| 53 | `in_60_70` | Calculated | Count of intervals where `60% ≤ in_bw < 70%` |
| 54 | `in_70_80` | Calculated | Count of intervals where `70% ≤ in_bw < 80%` |
| 55 | `in_50_100` | Calculated | Count of intervals where `in_bw ≥ 50%` |
| 56 | `in_60_100` | Calculated | Count of intervals where `in_bw ≥ 60%` |
| 57 | `in_70_100` | Calculated | Count of intervals where `in_bw ≥ 70%` |
| 58 | `in_80_100` | Calculated | Count of intervals where `in_bw ≥ 80%` |
| 59 | `in_90_100` | Calculated | Count of intervals where `in_bw ≥ 90%` |
| 60 | `out_0_50` | Calculated | Count of intervals where `out_bw < 50%` |
| 61 | `out_50_60` | Calculated | Count of intervals where `50% ≤ out_bw < 60%` |
| 62 | `out_60_70` | Calculated | Count of intervals where `60% ≤ out_bw < 70%` |
| 63 | `out_70_80` | Calculated | Count of intervals where `70% ≤ out_bw < 80%` |
| 64 | `out_50_100` | Calculated | Count of intervals where `out_bw ≥ 50%` |
| 65 | `out_60_100` | Calculated | Count of intervals where `out_bw ≥ 60%` |
| 66 | `out_70_100` | Calculated | Count of intervals where `out_bw ≥ 70%` |
| 67 | `out_80_100` | Calculated | Count of intervals where `out_bw ≥ 80%` |
| 68 | `out_90_100` | Calculated | Count of intervals where `out_bw ≥ 90%` |

> **Delta calculation:** Nokia Kafka sends **cumulative counters** (not deltas). OSS must track previous counter value per `(device-id, ifname)` and compute `delta = current - previous`. Handle counter wrap-around (64-bit counters).

---

## Table 2: `olt_uplink1d` — Uplink SFP Optical

**Kafka data path:** `device-specific-data.ietf-hardware:hardware-state.component[]`  
**Filter:** component with transceiver-link data on uplink ports (NTIO board components)  
**Interval:** 15 min

### Kafka Payload Sample
```json
{
  "ietf-hardware:hardware-state": {
    "component": [
      {
        "name": "Board-Ntio1.UPLINK_1",
        "bbf-hardware-transceivers:transceiver-link": {
          "diagnostics": {
            "nokia-hardware-transceivers-dbm:tx-power-dbm": 52,
            "nokia-hardware-transceivers-dbm:rx-power-dbm": -210,
            "tx-bias": 12338,
            "supply-voltage": 3353,
            "temperature": 331
          }
        }
      }
    ]
  }
}
```

> **Unit note:** Values are in raw integer units: tx-power-dbm in 0.1 dBm, tx-bias in μA, supply-voltage in mV, temperature in 0.1°C. Divide accordingly.

### Field Mapping

| # | db_colname | Source | Kafka / Logic |
|---|---|---|---|
| 1 | `tstamp` | Kafka | `device[].timestamp` — truncate to day |
| 2 | `ip` | device table | Lookup by OLT name from `device-id` |
| 3 | `ifindex` | intf table | Lookup `intf.ifindex` by matching port name to component name |
| 4 | `device` | device table | `device.name` |
| 5 | `vendor` | device table | `device.vendor` |
| 6 | `model` | device table | `device.model` |
| 7 | `txpwr` | Kafka | `transceiver-link.diagnostics.tx-power-dbm / 10` (dBm) |
| 8 | `rxpwr` | Kafka | `transceiver-link.diagnostics.rx-power-dbm / 10` (dBm) |
| 9 | `current` | Kafka | `transceiver-link.diagnostics.tx-bias / 1000` (mA) |
| 10 | `voltage` | Kafka | `transceiver-link.diagnostics.supply-voltage / 1000` (V) |
| 11 | `temp` | Kafka | `transceiver-link.diagnostics.temperature / 10` (°C) |
| 12 | `ifoper` | intf table | `intf.ifoper` |
| 13 | `sitename` | device table | `device.sitename` |
| 14 | `region` | device table | `device.region` |
| 15 | `province` | device table | `device.province` |
| 16 | `ifname` | intf table | `intf.ifname` |
| 17 | `moduleclass` | intf table | `intf.moduleclass` |
| 18 | `ifspeed` | intf table | `intf.ifspeed` |
| 19 | `dsttype` | intf table | `intf.dsttype` |
| 20 | `dstsite` | intf table | `intf.dstsite` |
| 21 | `dstport` | intf table | `intf.dstport` |
| 22 | `in_rate` | Kafka (traffic) | From same-interval uplink traffic message: `in_octets / meas` |
| 23 | `out_rate` | Kafka (traffic) | `out_octets / meas` |
| 24 | `max_rate` | Calculated | `MAX(in_rate, out_rate)` |
| 25 | `in_bw` | Calculated | `in_rate * 8 / ifspeed * 100` |
| 26 | `out_bw` | Calculated | `out_rate * 8 / ifspeed * 100` |
| 27 | `max_bw` | Calculated | `MAX(in_bw, out_bw)` |
| 28 | `in_err` | Kafka (traffic) | `statistics.in-discards` delta from traffic message |

> **Join strategy:** `olt_uplink1d` combines optical (hardware component data) and traffic (interface statistics) from the same 15-min window. Join on `(device-id, timestamp_bucket, port_name)` before writing to DB.

---

## Table 3: `olt_pon_1d` — OLT PON SFP Optical

**Kafka data path:** `device-specific-data.ietf-hardware:hardware-state.component[]`  
**Filter:** PON SFP components (`PON_x_GPON`, `PON_x_XGS`)  
**Interval:** 5 min (aggregate to 1d for DB)

### Kafka Payload Sample
```json
{
  "ietf-hardware:hardware-state": {
    "component": [
      {
        "name": "PONSFP_1",
        "bbf-hardware-transceivers:transceiver-link": {
          "wavelength": 1490,
          "diagnostics": {
            "nokia-hardware-transceivers-dbm:tx-power-dbm": 52,
            "nokia-hardware-transceivers-dbm:rx-power-dbm": -209,
            "tx-bias": 12338,
            "supply-voltage": 3353,
            "temperature": 331,
            "rssi-onu": [
              { "detected-serial-number": "ALCLF81E1CAE", "rssi": -209, "v-ani-ref": "ONT123" }
            ]
          }
        }
      }
    ]
  }
}
```

From §4.2.8 SFP inventory, PON optics data per wavelength:
```json
{
  "pon-sfp:output": {
    "pon-optics": [
      { "wavelength": 1490, "tx-power": "5.2", "tx-bias-current": "12.338", "module-voltage": "3.353", "module-temperature": "33.1", "name": "PON_1_GPON" },
      { "wavelength": 1577, "tx-power": "6.1", "tx-bias-current": "52.568", "module-voltage": "3.353", "module-temperature": "33.1", "name": "PON_1_XGS" }
    ]
  }
}
```

### Field Mapping

| # | db_colname | Source | Kafka / Logic |
|---|---|---|---|
| 1 | `tstamp` | Kafka | `device[].timestamp` — truncate to day |
| 2 | `ip` | device table | Lookup by OLT name |
| 3 | `ifindex` | ponport table | Lookup `ponport.ifindex` by fiber name |
| 4 | `device` | device table | `device.name` |
| 5 | `vendor` | device table | `device.vendor` |
| 6 | `model` | device table | `device.model` |
| 7 | `sitename` | device table | `device.sitename` |
| 8 | `region` | device table | `device.region` |
| 9 | `province` | device table | `device.province` |
| 10 | `ifname` | ponport table | `ponport.ifname` (fiber name) |
| 11 | `ifoper` | ponport table | `ponport.ifoper` |
| 12 | `ifspeed` | ponport table | `ponport.ifspeed` |
| 13 | `ponport` | ponport table | `ponport.ponport` |
| 14 | `moduleclass` | ponport table | `ponport.moduleclass` |
| 15 | `l1name` | ponport table | `ponport.l1sp` |
| 16 | `splitratio` | N/A | N/A — not available from Kafka; set null or from config |
| 17 | `pon_rxpwr` | Kafka | `diagnostics.rx-power-dbm / 10` — average across 5-min intervals (dBm at OLT) |
| 18 | `pon_txpwr1490` | Kafka | `pon-optics[wavelength=1490].tx-power` (dBm) |
| 19 | `pon_txpwr1577` | Kafka | `pon-optics[wavelength=1577].tx-power` (dBm) |
| 20 | `pon_current1490` | Kafka | `pon-optics[wavelength=1490].tx-bias-current` (mA) |
| 21 | `pon_current1577` | Kafka | `pon-optics[wavelength=1577].tx-bias-current` (mA) |
| 22 | `pon_voltage` | Kafka | `pon-optics[0].module-voltage` — same for both channels (V) |
| 23 | `pon_temp` | Kafka | `pon-optics[0].module-temperature` — same for both channels (°C) |
| 24 | `activecust` | Kafka | Count of `rssi-onu[]` entries with valid `rssi` — active ONTs on this PON |
| 25 | `in_pkt` | Kafka (traffic) | `bbf-interfaces-statistics-management:in-pkts` delta |
| 26 | `out_pkt` | Kafka (traffic) | `bbf-interfaces-statistics-management:out-pkts` delta |
| 27 | `in_err` | Kafka (traffic) | `statistics.in-discards` delta |
| 28 | `onu_in_biperr` | Kafka | Sum of `us-current-in-bip-errors` across ONTs on this fiber (from ONT detail) |
| 29 | `onu_out_biperr` | Kafka | Sum of `ds-current-in-bip-errors` across ONTs on this fiber |

> **Aggregation:** 5-min samples must be aggregated to daily. Use **average** for optical power/temperature/voltage; **sum** for packet/error counters; **max** for activecust.

---

## Table 4: `pontraffic1d` — PON Interface Traffic

**Kafka data path:** `device-specific-data.ietf-interfaces:interfaces-state.interface[]`  
**Filter:** interface `name` matches PON pattern (`CT_` prefix or fiber interface names)  
**Interval:** 5 min (`meas = 300`)

### Kafka Payload Sample (§4.4.5)
```json
{
  "ietf-interfaces:interfaces-state": {
    "interface": [
      {
        "name": "CT_QCENGMF2-1-9_9_GPON",
        "statistics": {
          "in-octets": "828635229",
          "out-octets": "41253252458",
          "in-discards": 399,
          "out-discards": 26837,
          "bbf-interfaces-statistics-management:in-pkts": "3782806",
          "bbf-interfaces-statistics-management:out-pkts": "28368388",
          "nokia-sdan-additional-statistics:in-dropped-bytes": "44694",
          "nokia-sdan-additional-statistics:out-dropped-bytes": "39700406",
          "nokia-sdan-xpon-statistics:xpon": {
            "out-unicast-gem-port-bytes": "41253147158",
            "out-unicast-gem-port-packets": "28367038",
            "out-unicast-gem-port-dropped-bytes": "39700406",
            "out-unicast-gem-port-dropped-packets": 26837,
            "out-incidental-broadcast-gem-port-bytes": "0",
            "out-incidental-broadcast-gem-port-packets": "0",
            "out-multicast-gem-port-bytes": "0",
            "out-multicast-gem-port-packets": "0"
          }
        }
      }
    ]
  }
}
```

### Field Mapping

| # | db_colname | Source | Kafka / Logic |
|---|---|---|---|
| 1 | `tstamp` | Kafka | `device[].timestamp` — truncate to day |
| 2 | `ip` | device table | Lookup by OLT name |
| 3 | `ifindex` | ponport table | Lookup `ponport.ifindex` by interface name |
| 4 | `ifspeed` | ponport table | `ponport.ifspeed` |
| 5 | `meas` | Fixed | `300` (5 min = 300 sec) |
| 6 | `cnt` | Calculated | Number of 5-min intervals aggregated to 1d |
| 7 | `deviceid` | device table | `device.id` |
| 8 | `device` | device table | `device.name` |
| 9 | `vendor` | device table | `device.vendor` |
| 10 | `model` | device table | `device.model` |
| 11 | `network` | device table | `device.network` |
| 12 | `topology` | device table | `device.topology` |
| 13 | `sitename` | device table | `device.sitename` |
| 14 | `province` | device table | `device.province` |
| 15 | `region` | device table | `device.region` |
| 16 | `name` | ponport table | `ponport.name` |
| 17 | `ifname` | Kafka | `interface[].name` |
| 18 | `ponport` | ponport table | `ponport.ponport` |
| 19 | `l1sp` | ponport table | `ponport.l1sp` |
| 20 | `in_octets` | Kafka | `statistics.in-octets` — **delta** |
| 21 | `out_octets` | Kafka | `statistics.out-octets` — **delta** |
| 22 | `in_rate` | Calculated | `in_octets / meas` (bytes/sec) |
| 23 | `out_rate` | Calculated | `out_octets / meas` (bytes/sec) |
| 24 | `max_rate` | Calculated | `MAX(in_rate, out_rate)` |
| 25 | `in_bw` | Calculated | `in_rate * 8 / ifspeed * 100` (%) |
| 26 | `out_bw` | Calculated | `out_rate * 8 / ifspeed * 100` (%) |
| 27 | `max_bw` | Calculated | `MAX(in_bw, out_bw)` |
| 28 | `in_err` | Kafka | `statistics.in-discards` — **delta** |
| 29 | `in_ucast_pkt` | N/A | N/A — Nokia does not provide upstream unicast at GEM level; set null |
| 30 | `in_bcast_pkt` | N/A | N/A — not available upstream; set null |
| 31 | `in_mcast_pkt` | N/A | N/A — not available upstream; set null |
| 32 | `in_pkt` | Kafka | `bbf-interfaces-statistics-management:in-pkts` — **delta** |
| 33 | `in_ucast_pct` | N/A | N/A — set null |
| 34 | `in_bcast_pct` | N/A | N/A — set null |
| 35 | `in_mcast_pct` | N/A | N/A — set null |
| 36 | `out_ucast_pkt` | Kafka | `nokia-sdan-xpon-statistics:xpon.out-unicast-gem-port-packets` — **delta** |
| 37 | `out_bcast_pkt` | Kafka | `nokia-sdan-xpon-statistics:xpon.out-incidental-broadcast-gem-port-packets` — **delta** |
| 38 | `out_mcast_pkt` | Kafka | `nokia-sdan-xpon-statistics:xpon.out-multicast-gem-port-packets` — **delta** |
| 39 | `out_pkt` | Kafka | `bbf-interfaces-statistics-management:out-pkts` — **delta** |
| 40 | `out_ucast_pct` | Calculated | `out_ucast_pkt / out_pkt * 100` |
| 41 | `out_bcast_pct` | Calculated | `out_bcast_pkt / out_pkt * 100` |
| 42 | `out_mcast_pct` | Calculated | `out_mcast_pkt / out_pkt * 100` |
| 43 | `in_err_pct` | Calculated | `in_err / in_pkt * 100` |
| 44 | `moduleclass` | ponport table | `ponport.moduleclass` |
| 45 | `vendorpn` | ponport table | `ponport.vendorpn` |
| 46 | `in_0_50` | Calculated | Count intervals where `in_bw < 50%` |
| 47 | `in_50_60` | Calculated | Count intervals where `50% ≤ in_bw < 60%` |
| 48 | `in_60_70` | Calculated | Count intervals where `60% ≤ in_bw < 70%` |
| 49 | `in_70_80` | Calculated | Count intervals where `70% ≤ in_bw < 80%` |
| 50 | `in_50_100` | Calculated | Count intervals where `in_bw ≥ 50%` |
| 51 | `in_60_100` | Calculated | Count intervals where `in_bw ≥ 60%` |
| 52 | `in_70_100` | Calculated | Count intervals where `in_bw ≥ 70%` |
| 53 | `in_80_100` | Calculated | Count intervals where `in_bw ≥ 80%` |
| 54 | `in_90_100` | Calculated | Count intervals where `in_bw ≥ 90%` |
| 55 | `out_0_50` | Calculated | Count intervals where `out_bw < 50%` |
| 56 | `out_50_60` | Calculated | Count intervals where `50% ≤ out_bw < 60%` |
| 57 | `out_60_70` | Calculated | Count intervals where `60% ≤ out_bw < 70%` |
| 58 | `out_70_80` | Calculated | Count intervals where `70% ≤ out_bw < 80%` |
| 59 | `out_50_100` | Calculated | Count intervals where `out_bw ≥ 50%` |
| 60 | `out_60_100` | Calculated | Count intervals where `out_bw ≥ 60%` |
| 61 | `out_70_100` | Calculated | Count intervals where `out_bw ≥ 70%` |
| 62 | `out_80_100` | Calculated | Count intervals where `out_bw ≥ 80%` |
| 63 | `out_90_100` | Calculated | Count intervals where `out_bw ≥ 90%` |

---

## Processing Notes

### Delta Calculation
Nokia Kafka sends **cumulative counters**. Must track last-seen value per `(device-id, interface-name)` and compute:
```
delta = current_value - previous_value
```
- If `delta < 0` → counter wrap-around; handle with 64-bit unsigned arithmetic
- If gap > 2 intervals → discard (device was down or missed messages)

### Daily Aggregation
Raw Kafka data arrives every 5 or 15 min. Aggregate to 1-day records:
- **Counters** (`in_octets`, `out_octets`, `in_pkt`, etc.) → `SUM` of all deltas for the day
- **Optical values** (`txpwr`, `rxpwr`, `temp`, etc.) → `AVG` across intervals
- **Rates/BW** → recalculate from daily sum: `in_rate = in_octets / (meas × cnt)`
- **Bucket counts** (`in_0_50`, etc.) → `SUM` across intervals

### Interface Name Mapping
Nokia PON interface names in Kafka (`CT_QCENGMF2-1-9_9_GPON`) differ from fiber names (`SWOLT000044.L1P1`). Build a mapping table during discovery: `kafka_interface_name → ponport.ifindex`.

Pattern: `CT_{OLT}-{chassis}-{lt}_{port}_{type}` → match to fiber `L{lt}P{port}`.

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

## Questions to Confirm with Nokia

1. What are the exact Kafka topic names for each PM data type (uplink traffic, uplink optical, PON traffic, PON optical)?
2. Are all PM metrics in a single topic or separate topics per data type?
3. What is the Kafka message format — JSON, Avro, or Protobuf? If Avro, provide schema registry URL.
4. What authentication method does the Kafka broker use?
5. Is IPFIX already enabled and configured on all OLTs in scope?
6. Are upstream unicast/broadcast/multicast packet counters available for PON interfaces (in addition to downstream)?
7. What is the exact unit/scale for optical diagnostic values (tx-power, tx-bias, voltage, temperature)?
8. Can Nokia provide sample raw Kafka messages for each topic?
9. What is the Kafka bootstrap server address and port?
10. Is the Kafka cluster reachable directly from the OSS server, or is a network path/VPN required?

---

## Status Legend

| Symbol | Meaning |
|---|---|
| ✅ | Confirmed from documentation |
| ⬜ | Not yet confirmed — need from Nokia/system owner |
