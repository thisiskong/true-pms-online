// Client for the tsdb service (service/tsdb), reached through the /tsdb dev proxy.
import { ApiError, qs, type Params } from "./client";

const BASE = "/tsdb/api";

export interface TsdbMetricStats {
  metric: string;
  series: number;
  tag_keys: string[];
  rows_24h: number;
  last_ts: number | null;      // ms
  last_ingest: number | null;  // ms
}

export type TsdbBackend = "clickhouse" | "postgres";

export interface TsdbStats {
  backend?: TsdbBackend;       // missing from services older than the Postgres backend
  database: string;
  rows: number;
  disk_bytes: number;
  uncompressed_bytes: number;
  parts: number;
  days: number;
  first_day: string | null;    // YYYYMMDD
  last_day: string | null;
  series: number;
  last_ingest: number | null;
  metrics: TsdbMetricStats[];
}

export interface TsdbFilter { type: string; tagk: string; filter: string; groupBy?: boolean }

export interface TsdbSubQuery {
  metric: string;
  aggregator: string;
  downsample?: string;
  tags?: Record<string, string>;
  filters?: TsdbFilter[];
  explicitTags?: boolean;
}

export interface TsdbQuery {
  start: number | string;
  end?: number | string;
  queries: TsdbSubQuery[];
  msResolution?: boolean;
  /** Echo each sub-query in its results; `query.index` is its position in `queries`. */
  showQuery?: boolean;
}

export interface TsdbResult {
  metric: string;
  tags: Record<string, string>;
  aggregateTags: string[];
  dps: Record<string, number | null>;
  query?: TsdbSubQuery & { index: number };
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let msg = res.status === 502 || res.status === 504 ? "tsdb service is not reachable (is it running on :8080?)" : res.statusText;
    try {
      const body = await res.json();
      msg = body?.error?.message ?? (typeof body.detail === "string" ? body.detail : msg);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const tsdbApi = {
  health: () => call<{ status: string; backend?: TsdbBackend; storage?: boolean; clickhouse?: boolean }>("/health"),
  stats: () => call<TsdbStats>("/stats"),
  suggest: (p: { type: "metrics" | "tagk" | "tagv"; q?: string; metric?: string; tagk?: string; max?: number }, signal?: AbortSignal) =>
    call<string[]>(`/suggest${qs(p as Params)}`, { signal }),
  query: (body: TsdbQuery, signal?: AbortSignal) =>
    call<TsdbResult[]>("/query", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal }),
};
