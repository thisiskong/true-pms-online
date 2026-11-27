import { useEffect, type ReactNode } from "react";

export function Modal({ title, subtitle, onClose, children, wide }: { title: string; subtitle?: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label={title}
        className={`flex max-h-[85vh] w-full ${wide ? "max-w-6xl" : "max-w-3xl"} flex-col rounded-xl border border-zinc-200 bg-white shadow-xl`}>
        <header className="flex items-start justify-between gap-3 px-5 pb-2 pt-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold tracking-tight text-zinc-900">{title}</h2>
            {subtitle && <div className="mt-0.5 text-xs text-zinc-500">{subtitle}</div>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900">
            <svg viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M4 4l8 8M12 4l-8 8" /></svg>
          </button>
        </header>
        <div className="overflow-auto px-5 pb-5 pt-2">{children}</div>
      </div>
    </div>
  );
}
