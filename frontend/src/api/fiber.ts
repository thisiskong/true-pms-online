// Fiber-score results (ml/fiber batch pipeline), served by backend/app/api/fiber.py.
import { get, qs, type Params } from "./client";

export type Level = "device" | "l1" | "l2";
export type Attribution = "drop" | "l2" | "l1" | "device" | "onu_hw";

export interface FiberRun {
  date: string;
  window: number;
  days: number;
  mean_conf: number;
  bad_onus: number;
}

export interface FiberSummary {
  date: string;
  window: number;
  days: string[];
  odn_date: string | null;
  onus: number;
  unscored_onus: number;
  mean_conf: number;
  histogram: Record<string, number>;
  bad_threshold: number;
  bad_onus: number;
  global_bad_rate: number;
  attributed: Partial<Record<Attribution, number>>;
  suspects: Partial<Record<Level, number>>;
  model: {
    model_date: string | null;
    holdout_mae_db: number | null;
    trained_mae_db: number | null;
    baseline_mae_db: number | null;
    mae_drift_db: number | null;
    feature_importance_gain: Record<string, number> | null;
    train_onus: number | null;
    holdout_onus: number | null;
  };
  inventory: { no_odn?: number; topology_mismatch?: number; l2_multi_device?: number; range_mismatch?: number };
  prev: { date: string; window: number; days: number; bad_onus: number; onus: number; suspects: Partial<Record<Level, number>> } | null;
}

export interface Suspect {
  device: string;
  device_id: number | null;
  l1name?: string;
  l2name?: string;
  vendor: string | null;
  model: string | null;
  region: string | null;
  province: string | null;
  sitename: string | null;
  n_onu: number;
  n_bad: number;
  n_l1?: number;
  n_l2?: number;
  n_bad_l2?: number;
  n_suspect_l1?: number;
  n_sibling_l1?: number;
  n_sibling_l2?: number;
  med_rx: number | null;
  med_excess_loss: number | null;
  med_peer_delta: number | null;
  bad_share: number;
  bad_rate_shrunk: number;
  p_value: number;
  impact: number;
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface SuspectPage {
  date: string;
  level: Level;
  items: Suspect[];
  page: number;
  size: number;
  total: number;
  facets: Record<"region" | "province" | "vendor", FacetValue[]>;
}

export interface TreeL2 {
  l2name: string | null;
  n_onu: number;
  n_bad: number;
  min_score: number | null;
  med_rx: number | null;
  med_excess_loss: number | null;
  med_peer_delta: number | null;
  suspect: boolean;
  attributed: Partial<Record<Attribution, number>>;
}

export interface TreePort {
  ponport: string;
  l1name: string | null;
  n_onu: number;
  n_bad: number;
  min_score: number | null;
  med_rx: number | null;
  med_excess_loss: number | null;
  suspect: boolean;
  l2: TreeL2[];
}

export interface FiberTree {
  date: string;
  device: string;
  device_id: number;
  device_suspect: boolean;
  n_onu: number;
  n_bad: number;
  n_ports: number;
  n_suspect_l1: number;
  n_suspect_l2: number;
  items: TreePort[];
  truncated: boolean;
}

export interface OnuScoreRow {
  ponport: string;
  ontid: string;
  l1name: string | null;
  l2name: string | null;
  vendor: string | null;
  score: number | null;
  conf: number | null;
  rx_med: number | null;
  expected_rx: number | null;
  excess_loss: number | null;
  peer_delta_l2: number | null;
  peer_delta_l1: number | null;
  bip_days: number | null;
  days_obs: number | null;
  hw_flag: boolean | null;
  bad: boolean | null;
  attributed_to: Attribution | null;
  // ONU hardware readings (window median, days outside the hw_ok range); absent in runs before 2026-11-25.
  hw_days?: number | null;
  tx_med?: number | null; voltage_med?: number | null; temp_med?: number | null; current_med?: number | null;
  hw_tx_days?: number | null; hw_voltage_days?: number | null; hw_temp_days?: number | null; hw_current_days?: number | null;
}

export interface BadOnuRow extends OnuScoreRow {
  device: string;
  device_id: number | null;
  province: string | null;
  region: string | null;
}

export interface OnuScore extends OnuScoreRow {
  device: string;
  model: string | null;
  moduleclass: string | null;
  s_power: number | null;
  s_excess: number | null;
  s_error: number | null;
  s_stability: number | null;
  rx_p10: number | null;
  rx_sd: number | null;
  rx_slope: number | null;
  rx_margin: number | null;
  overload: boolean | null;
  peer_n_l2: number | null;
  bip_obs: number | null;
  bip_log_mean: number | null;
  lc_days: number | null;
  lc_mean: number | null;
  len_km: number | null;
  split_db: number | null;
  splitratio: number | null;
  l1ratio: number | null;
  l2ratio: number | null;
  ranging: number | null;
  range_mismatch: boolean | null;
  dq_no_odn: boolean | null;
  dq_topo_mismatch: boolean | null;
  dq_l2_multi_device: boolean | null;
}

export interface OnuHistoryDay {
  date: string;
  rx: number | null;
  bip_in: number | null;
  lostcarrier: number | null;
  hw_flag: boolean | null;
  // ONU hardware readings (clean_onu); null when the ONU did not report them that day.
  tx?: number | null;
  voltage?: number | null;
  temp?: number | null;
  current?: number | null;
}

export interface OnuDetail {
  date: string;
  device_id: number;
  onu: OnuScore;
  history: OnuHistoryDay[];
  model_mae_db: number | null;
  window: number;
}

export const fiberApi = {
  runs: () => get<FiberRun[]>("/fiber/runs"),
  summary: (date?: string) => get<FiberSummary>("/fiber/summary", { date }),
  suspects: (p: Params, signal?: AbortSignal) => get<SuspectPage>("/fiber/suspects", p, signal),
  suspectsCsvUrl: (p: Params) => `/api/fiber/suspects.csv${qs(p)}`,
  tree: (deviceId: number, date?: string) => get<FiberTree>(`/fiber/devices/${deviceId}/tree`, { date }),
  onus: (deviceId: number, p: Params, signal?: AbortSignal) =>
    get<{ date: string; items: OnuScoreRow[]; page: number; size: number; total: number }>(`/fiber/devices/${deviceId}/onus`, p, signal),
  badOnus: (p: Params, signal?: AbortSignal) =>
    get<{ date: string; attributed_to: Attribution; items: BadOnuRow[]; page: number; size: number; total: number }>("/fiber/onus", p, signal),
  ponports: (deviceId: number) =>
    get<{ date: string; items: Record<string, { n_onu: number; n_bad: number; min_score: number | null }> }>(`/fiber/devices/${deviceId}/ponports`),
  onu: (deviceId: number, ponport: string, ontid: string, date?: string) =>
    get<OnuDetail>(`/fiber/devices/${deviceId}/onu`, { ponport, ontid, date }),
};
