// Mirrors backend/app/queries/models.py

export interface Page<T> {
  items: T[];
  page: number;
  size: number;
  total: number;
}

export interface DeviceRow {
  id: number;
  name: string | null;
  ip: string | null;
  vendor: string | null;
  model: string | null;
  network: string | null;
  topology: string | null;
  region: string | null;
  province: string | null;
  sitename: string | null;
  pollstatus: string | null;
  first: string | null;
  lastseen: string | null;
}

export interface Uptime {
  ip: string;
  polled_at: string | null;
  poll_method: string | null;
  uptime_seconds: number | null;
  uptime_text: string | null;
  last_reboot_at: string | null;
  last_ping_success_at: string | null;
  last_ping_rtt_ms: number | null;
}

export interface Device {
  id: number;
  name: string | null;
  ip: string | null;
  chassisid: string | null;
  descr: string | null;
  vendor: string | null;
  model: string | null;
  swversion: string | null;
  olttype: string | null;
  network: string | null;
  topology: string | null;
  region: string | null;
  province: string | null;
  sitename: string | null;
  latitude: number | null;
  longitude: number | null;
  rn: string | null;
  pn: string | null;
  dn: string | null;
  ringid: string | null;
  ringtopo: string | null;
  hop: string | null;
  uplink_ip1: string | null;
  uplink_site1: string | null;
  uplink_model1: string | null;
  uplink_ip2: string | null;
  uplink_site2: string | null;
  uplink_model2: string | null;
  a_homing_id: string | null;
  a_homing_site: string | null;
  b_homing_id: string | null;
  b_homing_site: string | null;
  c_homing_id: string | null;
  c_homing_site: string | null;
  agent: string | null;
  pollint: number | null;
  pollstatus: string | null;
  first: string | null;
  lastseen: string | null;
  last_modify_at: string | null;
  last_modify_by: string | null;
  uptime: Uptime | null;
}

export interface Interface {
  id: string;
  device_id: number | null;
  ifindex: string | null;
  ifname: string | null;
  ifalias: string | null;
  ifdescr: string | null;
  iftype: string | null;
  ifspeed: number | null;
  speed_text: string | null;
  ifadmin: string | null;
  ifoper: string | null;
  ifphyaddr: string | null;
  dstname: string | null;
  dstport: string | null;
  dstsite: string | null;
  dsttype: string | null;
  mediatype: string | null;
  vendorpn: string | null;
  moduleclass: string | null;
  pollstatus: string | null;
  first: string | null;
  lastseen: string | null;
}

export interface PonPort {
  id: string;
  device_id: number | null;
  ponport: string | null;
  ifindex: string | null;
  ifname: string | null;
  ifalias: string | null;
  ifdescr: string | null;
  iftype: string | null;
  ifspeed: number | null;
  speed_text: string | null;
  ifadmin: string | null;
  ifoper: string | null;
  ifconn: number | null;
  l1sp: string | null;
  l1_dl_max_bw: number | null;
  l1_ul_max_bw: number | null;
  dl_bw_remaining: string | null;
  ul_bw_remaining: string | null;
  moduleclass: string | null;
  vendorpn: string | null;
  /** Normalised optic class: B+, C+, C++, D, "absent" (no optic) or null (unknown). */
  optic_class: string | null;
  /** GPON or GPON+XGS-PON (combo optic). */
  optic_tech: string | null;
  /** Where optic_class came from: the port's moduleclass, or learned from its vendorpn. */
  optic_class_source: "moduleclass" | "vendorpn" | null;
  pollstatus: string | null;
  first: string | null;
  lastseen: string | null;
  onu_count: number;
  onu_capacity: number | null;
}

export interface Onu {
  ontid: string | null;
  accessid: string | null;
  devicesn: string | null;
  l1name: string | null;
  l2name: string | null;
  l1ratio: number | null;
  l2ratio: number | null;
  splitratio: number | null;
  l1len: number | null;
  l2len: number | null;
  dropwire: number | null;
  ranging: number | null;
  ranging_exclude: boolean | null;
  vendor: string | null;
  model: string | null;
  moduleclass: string | null;
  l2date: string | null;
  hsidate: string | null;
}

export interface InterfaceSummary {
  device_id: number;
  total: number;
  by_oper: Record<string, number>;
  by_admin: Record<string, number>;
  by_speed: Record<string, number>;
  by_type: Record<string, number>;
  with_neighbor: number;
}

export interface IntfChange {
  id: string;
  rev: number;
  device_id: number | null;
  ifindex: string | null;
  ifname: string | null;
  ifalias: string | null;
  ifoper: string | null;
  ifspeed: number | null;
  speed_text: string | null;
  first: string | null;
  lastseen: string | null;
}

export interface Neighbor {
  ifname: string | null;
  ifalias: string | null;
  ifoper: string | null;
  dstname: string | null;
  dstport: string | null;
  dstsite: string | null;
  neighbor_device_id: number | null;
  neighbor_ip: string | null;
}

export interface FacetValue {
  value: string | number | null;
  count: number;
}

export type Facets = Record<"vendor" | "model" | "network" | "topology" | "region" | "province" | "pollstatus", FacetValue[]>;

export interface FleetOverview {
  generated_at: string;
  devices: number;
  by_network: FacetValue[];
  by_topology: FacetValue[];
  by_vendor: FacetValue[];
  by_pollstatus: FacetValue[];
  uptime: { with_uptime: number; rebooted_24h: number; rebooted_7d: number; unreachable_24h: number };
  interfaces: { total: number; by_oper: FacetValue[] };
  interface_changes_24h: number;
}

export interface Kpis {
  generated_at: string;
  filtered: boolean;
  devices: number;
  uptime: { with_uptime: number; rebooted_24h: number; rebooted_7d: number; unreachable_24h: number };
  interface_changes_24h: number;
}

export interface ChatModel {
  id: string;
  name: string;
  input_per_mtok: number | null;
  output_per_mtok: number | null;
}

export interface ChatModels {
  provider: string;
  default: string;
  models: ChatModel[];
}

export interface Meta {
  chat_model: string;
  chat_configured: boolean;
}

/** GET /api/access/{accessid}: one subscriber by access id (circuit number). */
export interface AccessLookup {
  accessid: string;
  onu: {
    accessid: string;
    device_name: string;
    ponport: string;
    ontid: string;
    devicesn: string | null;
    l1name: string | null;
    l2name: string | null;
    l1ratio: number | null;
    l2ratio: number | null;
    splitratio: number | null;
    l1len: number | null;
    l2len: number | null;
    dropwire: number | null;
    ranging: number | null;
    moduleclass: string | null;
    l2date: string | null;
    hsidate: string | null;
  };
  device: {
    id: number | null;
    name: string;
    ip: string | null;
    vendor: string | null;
    model: string | null;
    region: string | null;
    province: string | null;
    sitename: string | null;
  };
  fiber: {
    date: string;
    score: number | null;
    conf: number | null;
    bad: boolean | null;
    attributed_to: "drop" | "l2" | "l1" | "device" | "onu_hw" | null;
    rx_med: number | null;
    expected_rx: number | null;
    excess_loss: number | null;
    peer_delta_l2: number | null;
    hw_flag: boolean | null;
  } | null;
  /** Why `fiber` is null (not in the ODN inventory, or no optical readings in the run window). */
  fiber_note: string | null;
  tickets: {
    items: Ticket[];
    truncated: boolean;
    data_from: string | null;
    data_to: string | null;
  };
}

export interface Ticket {
  ticketid: string;
  createtime: string | null;
  completetime: string | null;
  faulttype: string | null;
  faultcause: string | null;
  subcategory: string | null;
  faultstatus: string | null;
  networkdisp: string | null;
}

/** Row of /api/network/reboots and /api/network/unreachable: a device plus its uptime record. */
export type HealthRow = DeviceRow & { uptime: Uptime | null };

/** /api/interfaces: one row of the fleet-wide interface list. */
export interface FleetInterface {
  id: string;
  device_id: number | null;
  device_name: string | null;
  device_ip: string | null;
  name: string | null;
  altname: string | null;
  ifspeed: number | null;
  speed_text: string | null;
  ifoper: string | null;
  dsttype: string | null;
  dstsite: string | null;
  dstport: string | null;
  moduleclass: string | null;
  lastseen: string | null;
}

export type IntfFacets = Record<"ifoper" | "dsttype" | "moduleclass", FacetValue[]>;

/** /api/boards: one board (line card, control board, PSU, fan...) of a device. */
export interface BoardRow {
  id: string;
  device_id: number | null;
  device_name: string | null;
  device_ip: string | null;
  boardname: string | null;
  boardtype: string | null;
  boardrole: string | null;
  operstatus: string | null;
  first: string | null;
  lastseen: string | null;
}

export type BoardFacets = Record<"boardtype" | "boardrole" | "operstatus", FacetValue[]>;

/** /api/network/unstable: one interface with its change counts in the window (from the daily intf_rev poll). */
export interface UnstableRow {
  id: string;
  device_id: number;
  changes: number;
  oper_changes: number;
  down_changes: number;
  speed_changes: number;
  last_change: string;
  ifname: string | null;
  ifalias: string | null;
  ifoper: string | null;
  ifadmin: string | null;
  ifspeed: number | null;
  speed_text: string | null;
  device_name: string | null;
  device_ip: string | null;
  vendor: string | null;
  model: string | null;
  topology: string | null;
  region: string | null;
  province: string | null;
  sitename: string | null;
}
