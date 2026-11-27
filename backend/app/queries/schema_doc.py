"""Human/LLM-readable description of the phase-1 data (served by describe_schema and pms://schema)."""

SCHEMA_DOC = """\
# PMS Online data (phase 1, read-only)

All timestamps are Asia/Bangkok local time (UTC+07:00).

## device  (~50k rows) — network element inventory
- id: stable numeric device id (use this to refer to a device)
- name: SNMP sysName, e.g. "ATG0016-01_H910C-A"; ip: management IP (not unique alone; unique with chassisid)
- vendor: Huawei, ZTE, Nokia, Fiberhome, GCOM, Dasan, Raisecom, ...; model, swversion, olttype
- network: IPRAN, FTTx, BMA, SPECIAL, ...; topology: CPE, OLT, DN, AN, PN, AGN, "Grooming & Sub-AN", "BRAS - BMA", ...
- location: region, province, sitename, latitude, longitude
- hierarchy: rn (AGN/RN), pn (AN/PN), dn (Sub-AN/DN), ringid, ringtopo, hop,
  uplink_ip1/2 + uplink_site1/2 + uplink_model1/2, a/b/c_homing_id + _site
- pollstatus: Enable/Disable (user override wins over system value)
- first: first discovered; lastseen: last seen by discovery

## device_uptime  (~14.5k rows; joined to device by ip) — latest reachability per IP
- uptime (interval), last_reboot_at, last_ping_success_at, last_ping_rtt_ms, polled_at,
  poll_method (engine_oids | nokia_altiplano). Many devices (e.g. most CPEs) have no uptime row.

## intf  (~2.8M rows) — current interface state
- id = "<device_id>.<ifindex>"; device_id -> device.id
- ifname, ifalias (description), ifdescr, iftype, ifspeed (bit/s), ifadmin, ifoper (up, down, lowerLayerDown, dormant, notPresent)
- LLDP neighbor: dstname (remote sysName), dstport (remote port), dstsite, dsttype; optics: mediatype, vendorpn, moduleclass
- On average ~59 interfaces per device; a few devices have 7,000+.

## intf_rev  (~100k rows) — interface state history
- (id, rev): id = intf.id, rev increments on each change of ifoper or ifspeed
- each row is a state interval: the interface had ifoper/ifspeed from `first` until `lastseen`
- many changes for one interface in a short window = flapping

## odn_onu  (~3.4M rows) — subscriber ONUs and their ODN path
- accessid: access id / circuit number of the subscriber (unique, usually 10 digits, e.g. 9605163336)
- device (OLT name = device.name), ponport (e.g. "0-0-2-13"), ontid; devicesn = ONU serial
- l1name/l2name: L1 and L2 splitters; l1ratio/l2ratio/splitratio; l1len/l2len/dropwire (m); ranging (m)
- look up one subscriber with find_by_accessid

## ticket  (~1M rows, historical extract — check data_from/data_to) — subscriber trouble tickets
- ticketid, accessid, createtime, completetime, faulttype, faultcause, subcategory, faultstatus,
  networkdisp (network element/splitter named by the dispatcher). Text fields are often Thai.
"""
