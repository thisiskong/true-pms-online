import type {
  AccessLookup, ChatModels, Device, DeviceRow, Facets, FleetOverview, HealthRow, Kpis, Interface, InterfaceSummary, IntfChange, Meta, Neighbor, Onu, Page, PonPort, UnstableRow, FleetInterface, IntfFacets, BoardRow, BoardFacets,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export type Params = Record<string, string | number | boolean | null | undefined>;

export function qs(params: Params): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export async function get<T>(path: string, params: Params = {}, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`/api${path}${qs(params)}`, { signal });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  devices: (p: Params, signal?: AbortSignal) => get<Page<DeviceRow>>("/devices", p, signal),
  facets: (p: Params = {}, signal?: AbortSignal) => get<Facets>("/devices/facets", p, signal),
  device: (id: number) => get<Device>(`/devices/${id}`),
  interfaceSummary: (id: number) => get<InterfaceSummary>(`/devices/${id}/interfaces/summary`),
  interfaces: (id: number, p: Params, signal?: AbortSignal) => get<Page<Interface>>(`/devices/${id}/interfaces`, p, signal),
  ponports: (id: number) => get<{ items: PonPort[]; truncated: boolean }>(`/devices/${id}/ponports`),
  onus: (id: number, ponport: string) => get<{ items: Onu[]; truncated: boolean }>(`/devices/${id}/ponports/onus`, { ponport }),
  ponportRevs: (id: number, ponportId: string) =>
    get<{ items: IntfChange[]; truncated: boolean }>(`/devices/${id}/ponports/revisions`, { ponport_id: ponportId }),
  changes: (id: number, p: Params = {}) => get<{ items: IntfChange[]; truncated: boolean }>(`/devices/${id}/changes`, p),
  neighbors: (id: number) => get<{ items: Neighbor[]; truncated: boolean }>(`/devices/${id}/neighbors`),
  overview: () => get<FleetOverview>("/stats/overview"),
  kpis: (p: Params = {}, signal?: AbortSignal) => get<Kpis>("/stats/kpis", p, signal),
  meta: () => get<Meta>("/meta"),
  access: (accessid: string) => get<AccessLookup>(`/access/${encodeURIComponent(accessid)}`),
  reboots: (p: Params, signal?: AbortSignal) => get<Page<HealthRow>>("/network/reboots", p, signal),
  unreachable: (p: Params, signal?: AbortSignal) => get<Page<HealthRow>>("/network/unreachable", p, signal),
  fleetInterfaces: (p: Params, signal?: AbortSignal) => get<Page<FleetInterface>>("/interfaces", p, signal),
  boards: (p: Params, signal?: AbortSignal) => get<Page<BoardRow>>("/boards", p, signal),
  boardFacets: () => get<BoardFacets>("/boards/facets"),
  intfFacets: () => get<IntfFacets>("/interfaces/facets"),
  unstable: (p: Params, signal?: AbortSignal) => get<Page<UnstableRow>>("/network/unstable", p, signal),
  chatModels: () => get<ChatModels>("/chat/models"),
  exportUrl: (p: Params) => `/api/devices/export.csv${qs(p)}`,
};
