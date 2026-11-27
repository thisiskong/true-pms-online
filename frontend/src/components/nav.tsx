import type { ReactNode } from "react";

/** Top-menu structure. To ship a "soon" item: build its page + route, then delete `soon: true`. */
export interface NavLeaf {
  label: string;
  to: string;
  desc?: string;
  icon?: ReactNode;
  /** URL prefixes that mark this item (and its group) active; defaults to [to]. */
  match?: string[];
  /** Shown greyed out with a "soon" label, not clickable. */
  soon?: boolean;
  section?: string;
}

export interface NavGroup {
  label: string;
  items: NavLeaf[];
}

export type NavEntry = NavLeaf | NavGroup;

export const isGroup = (e: NavEntry): e is NavGroup => "items" in e;

export const isActive = (item: NavLeaf, path: string): boolean =>
  !item.soon && (item.match ?? [item.to]).some((m) => path === m || path.startsWith(`${m}/`));

// 16px stroke icons (lucide-style), inherit currentColor.
const I = ({ d }: { d: string }) => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d={d} />
  </svg>
);

export const NAV: NavEntry[] = [
  {
    label: "Network",
    items: [
      { label: "Devices", to: "/devices", desc: "Inventory, search, filters, CSV export",
        icon: <I d="M3 5h18v6H3zM3 13h18v6H3zM7 8h.01M7 16h.01" /> },
      { label: "Interfaces", to: "/interfaces", desc: "All interfaces fleet-wide: neighbor site, port, optics",
        icon: <I d="M5 3v6M9 3v6M15 3v6M19 3v6M3 9h18v5a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3zM12 17v4" /> },
      { label: "Boards", to: "/boards", desc: "Line cards, control boards, power and fans, with status",
        icon: <I d="M4 4h16v16H4zM9 4v16M4 9h5M4 14h5M13 8h4M13 12h4M13 16h4" /> },
      { section: "Health", label: "Reboots", to: "/network/reboots", desc: "Devices that rebooted recently",
        icon: <I d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5" /> },
      { section: "Health", label: "Unreachable devices", to: "/network/unreachable", desc: "No successful ping for a while",
        icon: <I d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /> },
      { section: "Health", label: "Unstable interfaces", to: "/network/unstable", desc: "Interfaces that change state most often",
        icon: <I d="M2 12h4l3-8 4 16 3-8h6" /> },
      { section: "Health", label: "Interface changes", to: "/network/changes", desc: "Recent up/down/speed changes, fleet-wide", soon: true,
        icon: <I d="M7 4 3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7" /> },
      { section: "Topology", label: "LLDP topology map", to: "/network/topology", desc: "Who connects to whom", soon: true,
        icon: <I d="M12 5a2 2 0 1 0 0-.01M5 19a2 2 0 1 0 0-.01M19 19a2 2 0 1 0 0-.01M12 7v4M12 11l-6 6M12 11l6 6" /> },
      { section: "Topology", label: "PON port capacity", to: "/network/ponports", desc: "PON ports near or over capacity, all OLTs", soon: true,
        icon: <I d="M4 20V10M10 20V4M16 20v-7M22 20H2" /> },
    ],
  },
  {
    label: "Subscriber",
    items: [
      { label: "Access id lookup", to: "/access", desc: "Subscriber ONU, ODN path and tickets by circuit no.",
        icon: <I d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.3-4.3" /> },
    ],
  },
  { label: "Fiber health", to: "/fiber" },
  { label: "Metrics", to: "/metrics" },
  { label: "Assistant", to: "/chat" },
];
