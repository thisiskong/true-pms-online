import { Fragment, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Link, useLocation } from "react-router";
import { isActive, type NavGroup } from "./nav";
import { cx } from "./ui";

/** Top-menu group: a button that opens a panel of links on click (not hover). */
export function NavMenu({ group }: { group: NavGroup }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const { pathname } = useLocation();
  const groupActive = group.items.some((i) => isActive(i, pathname));

  // Close on navigation.
  useEffect(() => setOpen(false), [pathname]);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const links = () => Array.from(root.current?.querySelectorAll<HTMLAnchorElement>("[data-navitem]") ?? []);
  const focusAt = (i: number) => { const l = links(); l[(i + l.length) % l.length]?.focus(); };

  const onButtonKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); requestAnimationFrame(() => focusAt(0)); }
  };
  const onPanelKey = (e: KeyboardEvent) => {
    const l = links(), i = l.indexOf(document.activeElement as HTMLAnchorElement);
    if (e.key === "ArrowDown") { e.preventDefault(); focusAt(i + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); focusAt(i - 1); }
    else if (e.key === "Home") { e.preventDefault(); focusAt(0); }
    else if (e.key === "End") { e.preventDefault(); focusAt(-1); }
  };

  let lastSection: string | undefined;
  return (
    <div ref={root} className="relative">
      <button ref={button} type="button" aria-haspopup="true" aria-expanded={open} aria-controls={panelId}
        onClick={() => setOpen((o) => !o)} onKeyDown={onButtonKey}
        className={cx("inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
          groupActive || open ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900")}>
        {group.label}
        <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden className={cx("transition-transform", open && "rotate-180")}>
          <path d="M5 7.5 10 12.5 15 7.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div id={panelId} onKeyDown={onPanelKey}
          className="fixed inset-x-2 top-14 z-30 mt-1 max-h-[calc(100vh-5rem)] overflow-y-auto rounded-xl border border-zinc-200 bg-white p-1.5 shadow-lg sm:absolute sm:inset-x-auto sm:left-0 sm:top-full sm:w-[380px]">
          {group.items.map((item) => {
            const heading = item.section && item.section !== lastSection ? item.section : null;
            lastSection = item.section;
            const active = isActive(item, pathname);
            const body = (
              <>
                <span className={cx("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border",
                  item.soon ? "border-zinc-100 text-zinc-300" : active ? "border-zinc-300 bg-white text-zinc-900" : "border-zinc-200 text-zinc-600")}>
                  {item.icon}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className={cx("text-sm font-medium", item.soon ? "text-zinc-400" : "text-zinc-900")}>{item.label}</span>
                    {item.soon && <span className="rounded bg-zinc-100 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-zinc-400">soon</span>}
                  </span>
                  {item.desc && <span className={cx("block text-xs", item.soon ? "text-zinc-300" : "text-zinc-500")}>{item.desc}</span>}
                </span>
              </>
            );
            return (
              <Fragment key={item.to}>
                {heading && (
                  <div className="mx-2 mb-1 mt-2 border-t border-zinc-100 pt-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">{heading}</div>
                )}
                {item.soon ? (
                  <div aria-disabled="true" title="Coming soon" className="flex cursor-not-allowed items-start gap-3 rounded-lg px-2.5 py-2">{body}</div>
                ) : (
                  <Link to={item.to} data-navitem aria-current={active ? "page" : undefined}
                    className={cx("flex items-start gap-3 rounded-lg px-2.5 py-2 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-zinc-400",
                      active ? "bg-zinc-100" : "hover:bg-zinc-50 focus:bg-zinc-50")}>
                    {body}
                  </Link>
                )}
              </Fragment>
            );
          })}
        </div>
      )}
    </div>
  );
}
