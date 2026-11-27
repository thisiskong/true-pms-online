import { lazy, Suspense, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { ChatModel } from "../../api/types";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage, Part, TablePart, ToolPart } from "../../hooks/useChat";
import { useChatCtx } from "../../hooks/chatContext";
import { fmtTime } from "../../lib/format";
import { cx, Spinner } from "../ui";

// echarts is large; load it only when a chart appears in the conversation.
const ChatChart = lazy(() => import("./ChatChart"));

const TOOL_LABEL: Record<string, string> = {
  search_devices: "Searching devices",
  get_device: "Looking up device",
  count_devices: "Counting devices",
  list_filter_values: "Listing filter values",
  get_device_uptime: "Reading uptime",
  list_recent_reboots: "Finding recent reboots",
  list_unreachable_devices: "Finding unreachable devices",
  interface_summary: "Summarizing interfaces",
  list_interfaces: "Listing interfaces",
  get_interface: "Reading interface",
  find_neighbors: "Finding LLDP neighbors",
  list_interface_changes: "Reading interface history",
  top_flapping_interfaces: "Finding flapping interfaces",
  fleet_overview: "Loading fleet overview",
  describe_schema: "Reading data dictionary",
  show_chart: "Drawing chart",
};

const EXAMPLES = [
  "How many OLTs are there per vendor?",
  "Which devices rebooted in the last 24 hours?",
  "Show the most flapping interfaces this week",
  "Which FTTx devices in region West are unreachable?",
];

const DEVICE_EXAMPLES = [
  "Summarize the health of this device",
  "Which interfaces are down?",
  "What changed on its interfaces in the last 7 days?",
  "Who are its LLDP neighbors?",
];

function ToolChip({ p }: { p: ToolPart }) {
  const label = TOOL_LABEL[p.name] ?? p.name;
  const [open, setOpen] = useState(false);
  return (
    <div className="text-xs">
      <button type="button" onClick={() => setOpen(!open)}
        className={cx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1",
          p.status === "error" ? "border-rose-200 bg-rose-50 text-rose-700" : "border-zinc-200 bg-zinc-50 text-zinc-600")}>
        {p.status === "running" ? <Spinner className="size-3" /> : <span>{p.status === "error" ? "⚠" : "✓"}</span>}
        <span>{label}</span>
        {p.status === "done" && p.rows != null && <span className="text-zinc-400">· {p.rows}{p.truncated ? "+" : ""} rows</span>}
        {p.ms != null && <span className="text-zinc-400">· {p.ms} ms</span>}
      </button>
      {open && (
        <pre className="mt-1 max-h-40 overflow-auto rounded-md bg-zinc-50 p-2 font-mono text-[11px] text-zinc-600">
          {p.name}({JSON.stringify(p.input ?? {}, null, 0)}){p.error ? `\n${p.error}` : ""}
        </pre>
      )}
    </div>
  );
}

const COL_LABEL: Record<string, string> = {
  "uptime.last_reboot_at": "last reboot", "uptime.uptime_text": "uptime", "uptime.last_ping_success_at": "last ping ok",
  speed_text: "speed", dstname: "neighbor", dstport: "nbr port", ifoper: "oper", ifadmin: "admin",
  neighbor_device_id: "nbr id", neighbor_ip: "nbr ip", down_changes: "downs", oper_changes: "up/down", speed_changes: "speed chg", device_name: "device", device_ip: "device ip",
};

function cell(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return fmtTime(v);
  return String(v);
}

function ResultTable({ p }: { p: TablePart }) {
  const [expanded, setExpanded] = useState(false);
  const rows = expanded ? p.rows : p.rows.slice(0, 8);
  const nameCol = p.columns.findIndex((c) => c === "name" || c === "device_name");
  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white">
      <div className="max-h-96 overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-zinc-50">
            <tr>{p.columns.map((c) => <th key={c} className="whitespace-nowrap px-2 py-1.5 text-left font-medium text-zinc-500">{COL_LABEL[c] ?? c}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-zinc-100">
                {r.map((v, j) => (
                  <td key={j} className="whitespace-nowrap px-2 py-1 text-zinc-700">
                    {j === nameCol && p.device_ids[i] != null
                      ? <Link to={`/devices/${p.device_ids[i]}`} className="text-brand-700 hover:underline">{cell(v)}</Link>
                      : cell(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-zinc-100 bg-zinc-50/60 px-2 py-1 text-[11px] text-zinc-500">
        <span>
          {p.rows.length} row{p.rows.length === 1 ? "" : "s"}
          {p.total != null && p.total > p.rows.length ? ` of ${p.total.toLocaleString()}` : p.truncated ? " (partial)" : ""}
        </span>
        {p.rows.length > 8 && (
          <button type="button" className="text-brand-700 hover:underline" onClick={() => setExpanded(!expanded)}>
            {expanded ? "Show less" : `Show all ${p.rows.length}`}
          </button>
        )}
      </div>
    </div>
  );
}

function PartView({ p }: { p: Part }) {
  switch (p.kind) {
    case "text":
      return <div className="prose-chat text-sm leading-relaxed text-zinc-800"><Markdown remarkPlugins={[remarkGfm]}>{p.text}</Markdown></div>;
    case "tool":
      return <ToolChip p={p} />;
    case "table":
      return <ResultTable p={p} />;
    case "chart":
      return (
        <Suspense fallback={<div className="flex h-72 items-center justify-center rounded-lg border border-zinc-200 bg-white"><Spinner /></div>}>
          <ChatChart p={p} />
        </Suspense>
      );
    case "notice":
      return <div className="text-xs italic text-zinc-500">{p.text}</div>;
    case "error":
      return <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{p.text}</div>;
  }
}

// "Anthropic: Claude Opus 5.5" -> provider "Anthropic", label "Claude Opus 5.5"
function splitName(m: ChatModel): [string, string] {
  const i = m.name.indexOf(": ");
  if (i > 0) return [m.name.slice(0, i), m.name.slice(i + 2)];
  const prov = m.id.includes("/") ? m.id.split("/")[0] : "Anthropic";
  return [prov.charAt(0).toUpperCase() + prov.slice(1), m.name];
}

const price = (v: number | null) => (v == null ? "?" : v < 1 ? `$${v.toFixed(2)}` : `$${+v.toFixed(2)}`);

function useModels() {
  return useQuery({ queryKey: ["chat-models"], queryFn: api.chatModels, staleTime: 10 * 60_000 });
}

function ModelPicker({ value, onChange, disabled }: { value: string | null; onChange: (id: string) => void; disabled?: boolean }) {
  // Custom popover (not a native <select>) so the menu matches the composer: rounded card, soft shadow, zinc tones.
  const q = useModels();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const models = q.data?.models ?? [];
  const current = value && models.some((m) => m.id === value) ? value : q.data?.default;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!rootRef.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  if (models.length < 2) return null;
  const groups = new Map<string, ChatModel[]>();
  for (const m of models) {
    const [prov] = splitName(m);
    groups.set(prov, [...(groups.get(prov) ?? []), m]);
  }
  const ordered = [...groups.values()].flat();
  const sel = models.find((m) => m.id === current);

  const show = () => { setActive(Math.max(0, ordered.findIndex((m) => m.id === current))); setOpen(true); };
  const pick = (id: string) => { onChange(id); setOpen(false); btnRef.current?.focus(); };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!open) {
      if (e.key === "ArrowUp" || e.key === "ArrowDown") { e.preventDefault(); show(); }
      return;
    }
    if (e.key === "Escape") { e.preventDefault(); setOpen(false); btnRef.current?.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => (i + 1) % ordered.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => (i - 1 + ordered.length) % ordered.length); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(ordered[active].id); }
    else if (e.key === "Tab") setOpen(false);
  };

  return (
    <div ref={rootRef} className="relative min-w-0" onKeyDown={onKey}>
      <button ref={btnRef} type="button" disabled={disabled} onClick={() => (open ? setOpen(false) : show())}
        aria-haspopup="listbox" aria-expanded={open} aria-label="Model"
        className={cx("flex min-w-0 max-w-[15rem] items-center gap-1 rounded-full py-1 pl-2.5 pr-2 text-xs font-medium text-zinc-600 outline-none transition-colors hover:bg-zinc-100 hover:text-zinc-900 focus-visible:ring-2 focus-visible:ring-zinc-300 disabled:cursor-default disabled:opacity-60",
          open && "bg-zinc-100 text-zinc-900")}>
        <span className="truncate">{sel ? splitName(sel)[1] : "Model"}</span>
        <svg viewBox="0 0 16 16" className={cx("size-3 shrink-0 text-zinc-400 transition-transform", open && "rotate-180")} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m4 6 4 4 4-4" /></svg>
      </button>
      {open && (
        <div role="listbox" aria-label="Model"
          className="absolute bottom-full left-0 z-30 mb-2 max-h-[min(24rem,60vh)] w-72 overflow-y-auto rounded-2xl border border-zinc-200 bg-white p-1.5 shadow-lg">
          {[...groups].map(([prov, ms]) => (
            <div key={prov}>
              <div className="px-2.5 pb-1 pt-2 text-[11px] font-medium text-zinc-400">{prov}</div>
              {ms.map((m) => {
                const idx = ordered.indexOf(m);
                const selected = m.id === current;
                return (
                  <div key={m.id} role="option" aria-selected={selected}
                    onMouseEnter={() => setActive(idx)} onClick={() => pick(m.id)}
                    className={cx("flex cursor-pointer items-center gap-2 rounded-xl px-2.5 py-2", idx === active && "bg-zinc-100")}>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 text-sm text-zinc-900">
                        <span className="truncate">{splitName(m)[1]}</span>
                        {m.id === q.data!.default && <span className="shrink-0 rounded-full border border-zinc-200 px-1.5 text-[10px] text-zinc-500">default</span>}
                      </div>
                      <div className="text-[11px] text-zinc-500">{price(m.input_per_mtok)} in · {price(m.output_per_mtok)} out per 1M tokens</div>
                    </div>
                    {selected && (
                      <svg viewBox="0 0 16 16" className="size-4 shrink-0 text-zinc-900" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m3.5 8.5 3 3 6-7" /></svg>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const fmtTok = (n: number) => (n < 1000 ? String(n) : n < 100_000 ? `${(n / 1000).toFixed(1)}k` : `${Math.round(n / 1000)}k`);
const fmtCost = (c: number) => (c === 0 ? "$0" : c < 0.01 ? `$${c.toFixed(4)}` : `$${c.toFixed(3)}`);

/** "20.3k in (8.8k cached) · 250 out · 2 calls · $0.0012". Exact counts come from the API after each model call;
 *  while an answer streams, the text received since the last call is added as a rough "+~N" (about 4 chars per token). */
function UsageLine({ usage, streamChars = 0 }: { usage?: Record<string, number>; streamChars?: number }) {
  const u = usage ?? {};
  const live = Math.round(streamChars / 4);
  const cached = u.cache_read_input_tokens ?? 0;
  const bits: string[] = [];
  if (u.input_tokens != null) bits.push(`${fmtTok(u.input_tokens)} in${cached ? ` (${fmtTok(cached)} cached)` : ""}`);
  bits.push(`${fmtTok(u.output_tokens ?? 0)}${live ? ` +~${fmtTok(live)}` : ""} out`);
  if (u.calls) bits.push(`${u.calls} call${u.calls > 1 ? "s" : ""}`);
  if (u.cost_usd != null) bits.push(fmtCost(u.cost_usd));
  return <span className="tabular-nums" title="Tokens used by this answer (input includes the system prompt, tool definitions and tool results)">{bits.join(" · ")}</span>;
}

function AnswerFooter({ m }: { m: ChatMessage }) {
  const q = useModels();
  if (m.pending) {
    if (!m.usage && !m.streamChars) return null;
    return (
      <div className="flex items-center gap-1.5 text-[11px] text-zinc-400">
        <Spinner className="size-2.5" /> <UsageLine usage={m.usage} streamChars={m.streamChars} />
      </div>
    );
  }
  if (!m.model) return null;
  const info = q.data?.models.find((x) => x.id === m.model);
  return (
    <div className="text-[11px] text-zinc-400">
      {info ? splitName(info)[1] : m.model}
      {m.usage && <> · <UsageLine usage={m.usage} /></>}
    </div>
  );
}

/** Running total for the whole conversation, shown under the composer. */
function ConversationUsage({ messages }: { messages: ChatMessage[] }) {
  let tokens = 0, cost = 0, hasCost = false;
  for (const m of messages) {
    const u = m.usage;
    if (!u) continue;
    tokens += (u.input_tokens ?? 0) + (u.output_tokens ?? 0) + Math.round((m.streamChars ?? 0) / 4);
    if (u.cost_usd != null) { cost += u.cost_usd; hasCost = true; }
  }
  if (!tokens) return null;
  return (
    <>
      <span aria-hidden>·</span>
      <span className="shrink-0 tabular-nums" title="Input + output tokens for this conversation so far">
        {fmtTok(tokens)} tokens{hasCost ? ` · ${fmtCost(cost)}` : ""}
      </span>
    </>
  );
}

function MessageView({ m }: { m: ChatMessage }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-3xl bg-zinc-100 px-4 py-2.5 text-sm text-zinc-900">{m.text}</div>
      </div>
    );
  }
  // Charts and tables render after the text of the answer so the narrative comes first.
  const tables = [...m.parts.filter((p) => p.kind === "chart"), ...m.parts.filter((p) => p.kind === "table")];
  const rest = m.parts.filter((p) => p.kind !== "table" && p.kind !== "chart");
  return (
    <div className="flex flex-col gap-2">
      {rest.map((p, i) => <PartView key={i} p={p} />)}
      {m.pending && rest.every((p) => p.kind !== "text") && (
        <div className="flex items-center gap-2 text-xs text-zinc-400"><Spinner className="size-3" /> Thinking…</div>
      )}
      {tables.map((p, i) => <PartView key={`t${i}`} p={p} />)}
      <AnswerFooter m={m} />
    </div>
  );
}

export function ChatPanel({ compact }: { compact?: boolean }) {
  const { messages, busy, send, stop, reset, device, setDevice, model, setModel } = useChatCtx();
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Grow the textarea with its content (up to max-h), like assistant-ui's composer.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [draft]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const submit = (text = draft) => {
    if (!text.trim() || busy) return;
    send(text, device?.id ?? null);
    setDraft("");
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const examples = device ? DEVICE_EXAMPLES : EXAMPLES;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className={cx("min-h-0 flex-1 overflow-y-auto", compact ? "px-4 py-4" : "px-6 py-6")}>
        <div className={cx("mx-auto flex flex-col gap-5", !compact && "max-w-3xl")}>
          {messages.length === 0 && (
            <div className={cx("flex flex-col gap-6", compact ? "pt-4" : "pt-[12vh]")}>
              <div className={cx(!compact && "text-center")}>
                <h2 className={cx("font-semibold tracking-tight text-zinc-900", compact ? "text-lg" : "text-2xl")}>
                  {device ? "What would you like to know about this device?" : "How can I help with the network?"}
                </h2>
                <p className="mt-1.5 text-sm text-zinc-500">
                  Answers come from read-only queries on devices, uptime, interfaces and interface history.
                </p>
              </div>
              <div className={cx("grid gap-2", !compact && "sm:grid-cols-2")}>
                {examples.map((ex) => (
                  <button key={ex} type="button" onClick={() => submit(ex)}
                    className="rounded-xl border border-zinc-200 bg-white px-4 py-3 text-left text-sm text-zinc-700 transition-colors hover:bg-zinc-50 hover:text-zinc-900">
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m) => <MessageView key={m.id} m={m} />)}
          <div ref={endRef} />
        </div>
      </div>

      <div className={cx(compact ? "px-3 pb-3 pt-1" : "px-4 pb-4 pt-1")}>
        <div className={cx("mx-auto", !compact && "max-w-3xl")}>
          <form
            onSubmit={(e) => { e.preventDefault(); submit(); }}
            onClick={(e) => { if (e.target === e.currentTarget) inputRef.current?.focus(); }}
            className="flex flex-col rounded-2xl border border-zinc-200 bg-white shadow-sm transition focus-within:border-zinc-300 focus-within:shadow-md">
            {device && (
              <div className="flex px-3 pt-2.5">
                <span className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-100 py-1 pl-2.5 pr-1.5 text-xs text-zinc-600">
                  <span className="text-zinc-400">Device</span>
                  <span className="max-w-[14rem] truncate font-medium text-zinc-700">{device.name ?? `#${device.id}`}</span>
                  <button type="button" onClick={() => setDevice(null)} title="Remove device context"
                    className="rounded p-0.5 text-zinc-400 hover:bg-zinc-200 hover:text-zinc-700">
                    <svg viewBox="0 0 16 16" className="size-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M4 4l8 8M12 4l-8 8" /></svg>
                  </button>
                </span>
              </div>
            )}
            <textarea ref={inputRef} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey}
              rows={1} autoFocus={!compact} aria-label="Message"
              placeholder="Send a message…"
              className="max-h-48 min-h-[44px] w-full resize-none overflow-y-auto bg-transparent px-4 pb-1 pt-3 text-sm text-zinc-800 outline-none placeholder:text-zinc-400" />
            <div className="flex items-center justify-between gap-2 px-2 pb-2">
              <ModelPicker value={model} onChange={setModel} disabled={busy} />
              {busy ? (
                <button type="button" onClick={stop} title="Stop generating" aria-label="Stop generating"
                  className="grid size-8 shrink-0 place-items-center rounded-full bg-zinc-900 text-white transition hover:bg-zinc-700">
                  <svg viewBox="0 0 16 16" className="size-3" fill="currentColor"><rect x="3" y="3" width="10" height="10" rx="1.5" /></svg>
                </button>
              ) : (
                <button type="submit" disabled={!draft.trim()} title="Send (Enter)" aria-label="Send message"
                  className="grid size-8 shrink-0 place-items-center rounded-full bg-zinc-900 text-white transition hover:bg-zinc-700 disabled:bg-zinc-200 disabled:text-zinc-400">
                  <svg viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" /></svg>
                </button>
              )}
            </div>
          </form>
          <div className="mt-1.5 flex items-center justify-center gap-3 px-1 text-[11px] text-zinc-400">
            <span className="truncate">AI answers can be wrong. Check important numbers.</span>
            <ConversationUsage messages={messages} />
            {messages.length > 0 && (
              <>
                <span aria-hidden>·</span>
                <button type="button" onClick={reset} className="shrink-0 hover:text-zinc-700">New conversation</button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
