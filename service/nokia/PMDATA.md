# output
1. traffic60m     - olt uplink usage metrics
2. oltuplink60m   - olt uplink sfp metrics
4. oltpon60m      - olt ponport sfp metrics
3. pontraffic60m  - olt ponport usage metrics
5. onupon60m      - onu ponport usage and sfp metrics


# json format
## traffic60m.json
{
    "collectTime": "2026-06-09T03:00:00",
    "ifindex": "70",
    "ifoper": "down",
    "ifspeed": 1000000000,
    "in_bw": 0,
    "in_err": 0,
    "in_err1": 0,
    "in_err2": 0,
    "in_flg": "normal",
    "in_octets": 0,
    "in_octets1": 0,
    "in_octets2": 0,
    "in_rate": 0,
    "ip": "10.177.175.87",
    "meas": 3595,
    "out_bw": 0,
    "out_flg": "normal",
    "out_octets": 0,
    "out_octets1": 0,
    "out_octets2": 0,
    "out_rate": 0
}

## oltuplink60m.json
{
    "collectTime": "2025-09-19T18:00:13",
    "current": 80.16,
    "device": "BKK25014GO0",
    "ifindex": "234905664",
    "ifname": "ethernet0/3/1",
    "ifoper": "down",
    "ifspeed": 10000000000,
    "ip": "10.238.37.6",
    "meas": 0,
    "model": "MA5800",
    "rxpwr": -40,
    "temp": 54.25,
    "txpwr": -21.67491,
    "vendor": "Huawei",
    "voltage": 3.2464999999999997
}

## oltpon60m.json
{
    "collectTime": "2026-06-11T03:00:14",
    "device": "SMP03044G00",
    "ifindex": "4194315264",
    "ifname": "GPON 0/1/12",
    "ifoper": "down",
    "ifspeed": 2488000000,
    "ip": "10.238.41.30",
    "meas": 0,
    "model": "MA5800-X2",
    "pon_current1490": 34,
    "pon_current1577": -0.001,
    "pon_rxpwr": null,
    "pon_temp": 53,
    "pon_txpwr1490": 3.63,
    "pon_txpwr1577": null,
    "pon_voltage": 3.21,
    "ponport": "0-0-1-12",
    "vendor": "Huawei"
}

## pontraffic60m.json
{
    "collectTime": "2026-06-11T01:00:20",
    "device": "SMP02008GO0",
    "ifindex": "4194323712",
    "ifname": "GPON 0/2/13",
    "ifoper": "down",
    "ifspeed": 2488000000,
    "in_bcast_pct": 0,
    "in_bcast_pkt": 0,
    "in_bcast_pkt1": 0,
    "in_bcast_pkt2": 0,
    "in_err": 0,
    "in_err1": 0,
    "in_err2": 0,
    "in_err_pct": null,
    "in_mcast_pct": 0,
    "in_mcast_pkt": 0,
    "in_mcast_pkt1": 0,
    "in_mcast_pkt2": 0,
    "in_octets": 0,
    "in_octets1": 0,
    "in_octets2": 0,
    "in_pkt": 0,
    "in_ucast_pct": 0,
    "in_ucast_pkt": 0,
    "in_ucast_pkt1": 0,
    "in_ucast_pkt2": 0,
    "ip": "10.238.5.7",
    "meas": 3603,
    "model": "MA5800-X2",
    "out_bcast_pct": 0,
    "out_bcast_pkt": 0,
    "out_bcast_pkt1": 0,
    "out_bcast_pkt2": 0,
    "out_mcast_pct": 0,
    "out_mcast_pkt": 0,
    "out_mcast_pkt1": 0,
    "out_mcast_pkt2": 0,
    "out_octets": 0,
    "out_octets1": 0,
    "out_octets2": 0,
    "out_pkt": 0,
    "out_ucast_pct": 0,
    "out_ucast_pkt": 0,
    "out_ucast_pkt1": 0,
    "out_ucast_pkt2": 0,
    "ponport": "0-0-2-13",
    "vendor": "Huawei"
}

## onupon60m.json
{
    "collectTime": "2026-06-10T16:01:12",
    "device": "QCENGHW5603",
    "ifindex": "4194345216",
    "ifname": "GPON 0/5/1",
    "ip": "10.238.77.241",
    "meas": 57598,
    "model": "MA5603T",
    "ontid": "9",
    "onu_current": null,
    "onu_in_biperr": 0,
    "onu_in_octets": 0,
    "onu_in_pkt": null,
    "onu_in_pkterr": 0,
    "onu_lastdowncause": "unknown",
    "onu_lastdowntime": null,
    "onu_lastseen": null,
    "onu_lastuptime": null,
    "onu_out_biperr": 0,
    "onu_out_octets": 0,
    "onu_out_pkt": null,
    "onu_out_pkterr": 0,
    "onu_rxpwr": null,
    "onu_serial": null,
    "onu_status": null,
    "onu_temp": null,
    "onu_txpwr": null,
    "onu_voltage": null,
    "pon_rxpwr": null,
    "ponport": "0-0-5-1",
    "ranging": null,
    "vendor": "Huawei"
}


# tsdb format
Format: <name> <unixtime> <value> ip=<ip> intf=<ifindex>
Sample: txpwr 1780858807263 -2.670000 ip=10.237.35.14 intf=393728
        rxpwr 1780858807263 -5.690000 ip=10.237.35.14 intf=393728


## traffic60m.tsdb
name:
  in_bw
  in_err
  in_octets
  in_rate
  out_bw
  out_octets
  out_rate

## oltuplink60m.tsdb
name:
  current
  rxpwr
  temp
  txpwr
  voltage

## oltpon60m.tsdb
name:
  pon_current1490
  pon_current1577
  pon_temp
  pon_txpwr1490
  pon_txpwr1577
  pon_voltage

## pontraffic60m.tsdb
name:
  in_bcast_pct
  in_bcast_pkt
  in_bw
  in_err
  in_err_pct
  in_mcast_pct
  in_mcast_pkt
  in_octets
  in_pkt
  in_rate
  in_ucast_pct
  in_ucast_pkt
  out_bcast_pct
  out_bcast_pkt
  out_bw
  out_mcast_pct
  out_mcast_pkt
  out_octets
  out_pkt
  out_rate
  out_ucast_pct
  out_ucast_pkt