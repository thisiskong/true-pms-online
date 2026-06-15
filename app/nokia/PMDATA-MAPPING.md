# Nokia Kafka → PMS Output Mapping

## Target Output Formats (from PMDATA.md)

### `oltuplink60m.json` — one record per uplink port per OLT

| Field | Type | Description |
|---|---|---|
| `collectTime` | string | Collection timestamp |
| `current` | float | Optical current (mA) |
| `device` | string | Device name |
| `ifindex` | string | Interface index |
| `ifname` | string | Interface name |
| `ifoper` | string | Oper status |
| `ifspeed` | int | Port speed (bps) |
| `ip` | string | Device IP |
| `meas` | int | Measurement interval (seconds) |
| `model` | string | Device model |
| `rxpwr` | float | Rx optical power (dBm) |
| `temp` | float | SFP temperature (°C) |
| `txpwr` | float | Tx optical power (dBm) |
| `vendor` | string | Vendor name |
| `voltage` | float | SFP supply voltage (V) |

### `traffic60m.json` — one record per interface per OLT

| Field | Type | Description |
|---|---|---|
| `collectTime` | string | Collection timestamp |
| `ifindex` | string | Interface index |
| `ifoper` | string | Oper status |
| `ifspeed` | int | Port speed (bps) |
| `in_bw` / `out_bw` | float | Bandwidth utilization |
| `in_err` / `in_err1` / `in_err2` | int | Error counters |
| `in_flg` / `out_flg` | string | Status flag (`normal` / `overflow`) |
| `in_octets` / `out_octets` | int | Cumulative byte counters |
| `in_octets1` / `in_octets2` | int | Sub-counters (unicast/mcast split) |
| `out_octets1` / `out_octets2` | int | Sub-counters |
| `in_rate` / `out_rate` | float | Current rate (bps or Mbps) |
| `ip` | string | Device IP |
| `meas` | int | Measurement interval (seconds) |

---

## Kafka Message Types

Each file is NDJSON — one JSON object per line. Two distinct message schemas appear:

### Type 1 — xPON GEM port statistics

Root key: `ietf-interfaces:interfaces-state`

```
device-id: "SMK01058GO0.LT1"          → device name + LT slot
timestamp: "2026-06-09T00:20:00+0000"
interface[].name: "CT_SMK01058GO0-1-1_1_GPON"
  → pattern: CT_{device}-{lt}-{ponidx}_{ponidx}_{tech}
  → tech: GPON or XGS

statistics.nokia-sdan-xpon-statistics:xpon:
  out-unicast-gem-port-bytes           → downstream unicast bytes to ONTs
  out-unicast-gem-port-packets         → downstream unicast packets
  out-unicast-gem-port-dropped-bytes   → dropped bytes
  out-unicast-gem-port-dropped-packets → dropped packets
  out-incidental-broadcast-gem-port-* → broadcast (observed always 0)
  out-multicast-gem-port-*            → multicast (observed always 0)
```

### Type 2 — Hardware sensors

Root key: `ietf-hardware:hardware-state`

```
device-id: "RET13002G00"
timestamp: "2026-06-09T00:20:22+0000"
hardware-state.component[]:
  name: "Board-Fan.FANSPEEDx"  → fan RPM
  name: "Board-Psu*.TEMP1"     → PSU temperature (°C)
  name: "Board.TEMPx"          → board temperature (°C)
  name: "SFP_x.TEMP1/TEMP2"   → SFP temperature (°C)
  sensor-data.value: <int>     → sensor reading
```

---

## Field Mapping: Kafka → Output

### Type 1 → `traffic60m.json` (PON port downstream traffic)

| Output Field | Kafka Source | Notes |
|---|---|---|
| `collectTime` | `timestamp` | Convert to local or keep UTC |
| `ip` | — | Needs device→IP lookup from discovery |
| `ifindex` | — | Not in Kafka; needs RC-Proxy or SNMP |
| `ifname` | `interface[].name` | Parse: `CT_{device}-{lt}-{ponidx}_{ponidx}_{tech}` → derive PON port id |
| `ifoper` | — | Not in Kafka; default `up` or lookup |
| `ifspeed` | — | Derive from xpon-type (gpon=2488000000, xgs=10000000000) |
| `out_octets` | Derived | `out_octets2 - out_octets1` (delta bytes for this interval) |
| `out_octets1` | `out-unicast-gem-port-bytes` (previous message) | Previous cumulative counter value |
| `out_octets2` | `out-unicast-gem-port-bytes` (current message) | Current cumulative counter value |
| `in_octets` | — | **Not in Kafka** — upstream counters absent from this topic |
| `in_octets1` / `in_octets2` | — | **Not in Kafka** |
| `out_rate` | Derived | Calculate from delta bytes / meas interval |
| `in_rate` | — | **Not in Kafka** |
| `out_bw` | Derived | `out_rate / ifspeed * 100` |
| `in_bw` | — | **Not in Kafka** |
| `in_err` / `in_err1` / `in_err2` | — | **Not in Kafka** |
| `in_flg` / `out_flg` | Derived | `overflow` if dropped > 0, else `normal` |
| `meas` | Derived | Interval between timestamps (5 min = 300s per filename cadence) |

### Type 2 → `oltuplink60m.json` (SFP sensors)

| Output Field | Kafka Source | Notes |
|---|---|---|
| `collectTime` | `timestamp` | Convert to local or keep UTC |
| `device` | `device-id` | Device name |
| `ip` | — | Needs device→IP lookup from discovery |
| `ifname` | Derived from `SFP_x` index | Map SFP slot index to port name |
| `ifindex` | — | Not in Kafka |
| `temp` | `SFP_x.TEMP1` sensor-data.value | SFP temperature (°C) |
| `model` | — | Not in Kafka; needs inventory lookup |
| `vendor` | — | Hardcode `Nokia` |
| `ifoper` | — | Not in Kafka |
| `ifspeed` | — | Needs uplink port inventory |
| `rxpwr` | — | **Not in this Kafka topic** |
| `txpwr` | — | **Not in this Kafka topic** |
| `current` | — | **Not in this Kafka topic** |
| `voltage` | — | **Not in this Kafka topic** |
| `meas` | Derived | 300s per filename cadence |

---

## Gaps Summary

| Output Field | Status | Resolution |
|---|---|---|
| `ip` | Missing from Kafka | Lookup from discovery output (`device.jsonl`) |
| `ifindex` | Missing from Kafka | RC-Proxy (not deployed) or SNMP poll |
| `in_octets` / `in_rate` / `in_bw` | Missing from Kafka | Upstream GEM stats not in this topic |
| `rxpwr` / `txpwr` / `current` / `voltage` | Missing from Kafka | SFP optical diagnostics not in this topic |
| `model` | Missing from Kafka | Discovery inventory lookup |
| `ifoper` | Missing from Kafka | Default `up` or separate topic |
| `in_err*` | Missing from Kafka | Not available in xPON GEM stats |

The Kafka topic covers **downstream GEM port byte/packet counters** (Type 1) and **hardware sensors** (Type 2) only. Upstream traffic, SFP optical diagnostics, and interface indexes require separate data sources.