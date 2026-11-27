import type { ReactNode } from "react";

export function cx(...c: (string | false | null | undefined)[]): string {
  return c.filter(Boolean).join(" ");
}

export function Card({ title, actions, children, className, bodyClass }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={cx("rounded-xl border border-zinc-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 px-5 pb-1 pt-4">
          <h2 className="text-sm font-semibold tracking-tight text-zinc-900">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={cx("px-5 pb-5 pt-3", bodyClass)}>{children}</div>
    </section>
  );
}

/** Page container shared by the Network pages (and the other top-level pages), so they all have the same width. */
export const PAGE_CLS = "mx-auto flex w-full max-w-[1600px] flex-col gap-4 p-4 md:p-6";

const OPER_STYLE: Record<string, string> = {
  up: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  down: "bg-rose-50 text-rose-700 ring-rose-600/20",
  lowerLayerDown: "bg-amber-50 text-amber-700 ring-amber-600/20",
  dormant: "bg-zinc-100 text-zinc-600 ring-zinc-500/20",
  notPresent: "bg-zinc-100 text-zinc-500 ring-zinc-500/20",
  Enable: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  Disable: "bg-zinc-100 text-zinc-500 ring-zinc-500/20",
  // board.operstatus (vendor-specific wording)
  normal: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  present: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  inService: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  enabled: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  offline: "bg-rose-50 text-rose-700 ring-rose-600/20",
  hwOffline: "bg-rose-50 text-rose-700 ring-rose-600/20",
  fault: "bg-rose-50 text-rose-700 ring-rose-600/20",
  absent: "bg-zinc-100 text-zinc-500 ring-zinc-500/20",
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-zinc-400">—</span>;
  return (
    <span className={cx("inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset", OPER_STYLE[value] ?? "bg-zinc-100 text-zinc-600 ring-zinc-500/20")}>
      {value}
    </span>
  );
}

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "brand" | "amber" | "rose" }) {
  const tones = {
    slate: "bg-zinc-100 text-zinc-700",
    brand: "bg-brand-50 text-brand-700",
    amber: "bg-amber-50 text-amber-700",
    rose: "bg-rose-50 text-rose-700",
  };
  return <span className={cx("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx("size-4 animate-spin text-zinc-500", className)} viewBox="0 0 24 24" fill="none" aria-label="loading">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">Failed to load: {msg}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-8 text-center text-sm text-zinc-400">{children}</div>;
}

export function Button({ children, onClick, variant = "secondary", disabled, type = "button", title, className }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "ghost"; disabled?: boolean;
  type?: "button" | "submit"; title?: string; className?: string;
}) {
  const v = {
    primary: "bg-zinc-900 text-white shadow-sm hover:bg-zinc-700 disabled:bg-zinc-300",
    secondary: "border border-zinc-200 bg-white text-zinc-900 shadow-sm hover:bg-zinc-100 disabled:text-zinc-300",
    ghost: "text-zinc-700 hover:bg-zinc-100 hover:text-zinc-900 disabled:text-zinc-300",
  };
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled}
      className={cx("inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm font-medium transition-colors disabled:cursor-not-allowed", v[variant], className)}>
      {children}
    </button>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-xs font-medium text-zinc-700">{label}</span>
      {children}
    </label>
  );
}

export const inputCls =
  "h-8 w-full rounded-md border border-zinc-200 bg-white px-2.5 text-sm text-zinc-900 shadow-xs outline-none transition-shadow placeholder:text-zinc-400 focus:border-zinc-400 focus:ring-[3px] focus:ring-zinc-400/30";

export function Pagination({ page, size, total, onPage, onSize }: {
  page: number; size: number; total: number; onPage: (p: number) => void; onSize?: (s: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / size));
  const from = total === 0 ? 0 : (page - 1) * size + 1;
  const to = Math.min(total, page * size);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 px-1 pt-3 text-sm text-zinc-500">
      <span>{from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}</span>
      <div className="flex items-center gap-1">
        {onSize && (
          <select className={cx(inputCls, "mr-2 w-auto")} value={size} onChange={(e) => onSize(Number(e.target.value))} aria-label="rows per page">
            {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n} / page</option>)}
          </select>
        )}
        <Button variant="ghost" disabled={page <= 1} onClick={() => onPage(1)} title="First">«</Button>
        <Button variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)} title="Previous">‹</Button>
        <span className="whitespace-nowrap px-2 tabular-nums">{page.toLocaleString()} / {pages.toLocaleString()}</span>
        <Button variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)} title="Next">›</Button>
        <Button variant="ghost" disabled={page >= pages} onClick={() => onPage(pages)} title="Last">»</Button>
      </div>
    </div>
  );
}
