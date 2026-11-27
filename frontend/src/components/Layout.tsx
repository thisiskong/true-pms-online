import { NavLink, Outlet, useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useChatCtx } from "../hooks/chatContext";
import { ChatPanel } from "./chat/ChatPanel";
import { isGroup, NAV } from "./nav";
import { NavMenu } from "./NavMenu";
import { cx } from "./ui";

function NavItem({ to, children }: { to: string; children: string }) {
  return (
    <NavLink to={to}
      className={({ isActive }) => cx("rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        isActive ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900")}>
      {children}
    </NavLink>
  );
}

export function Layout() {
  const { drawerOpen, setDrawerOpen } = useChatCtx();
  const loc = useLocation();
  const onChatPage = loc.pathname.startsWith("/chat");
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });

  return (
    <div className="flex h-full flex-col">
      {/* relative z-30: backdrop-blur makes the header a stacking context, so the Network menu panel can only
          sit above page content (tables use `relative`) if the header itself does. */}
      <header className="relative z-30 flex h-14 shrink-0 items-center gap-2 border-b border-zinc-200 bg-white/80 px-3 text-zinc-900 backdrop-blur sm:gap-4 sm:px-5">
        <NavLink to="/devices" className="flex items-center gap-2 font-semibold tracking-tight">
          <img src="/true-logo.png" alt="True" className="h-7 w-auto" />
        </NavLink>
        <nav className="flex items-center gap-1" aria-label="Main">
          {NAV.map((e) => (isGroup(e) ? <NavMenu key={e.label} group={e} /> : <NavItem key={e.to} to={e.to}>{e.label}</NavItem>))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {meta.data && !meta.data.chat_configured && (
            <span className="hidden text-xs text-amber-600 sm:inline" title="Set ANTHROPIC_API_KEY in backend/.env">assistant not configured</span>
          )}
          {!onChatPage && (
            <button type="button" onClick={() => setDrawerOpen(!drawerOpen)}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-zinc-900 px-3.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-zinc-700">
              ✦ Ask AI
            </button>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
        {drawerOpen && !onChatPage && (
          <aside className="fixed inset-0 top-14 z-20 flex w-full flex-col border-l border-zinc-200 bg-white shadow-xl sm:static sm:z-auto sm:w-[440px] sm:shadow-none">
            <div className="flex h-11 shrink-0 items-center justify-between border-b border-zinc-200 px-4">
              <span className="text-sm font-semibold text-zinc-700">Assistant</span>
              <div className="flex items-center gap-1">
                <NavLink to="/chat" className="rounded-md px-2 py-1 text-xs font-medium text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900" onClick={() => setDrawerOpen(false)}>Expand</NavLink>
                <button type="button" onClick={() => setDrawerOpen(false)} className="rounded-md px-2 py-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900" aria-label="Close assistant">✕</button>
              </div>
            </div>
            <div className="min-h-0 flex-1"><ChatPanel compact /></div>
          </aside>
        )}
      </div>
    </div>
  );
}
