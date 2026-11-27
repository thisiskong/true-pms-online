import { useCallback, useRef, useState } from "react";

export interface ToolPart {
  kind: "tool";
  id: string;
  name: string;
  status: "running" | "done" | "error";
  input?: unknown;
  rows?: number | null;
  ms?: number;
  truncated?: boolean;
  error?: string | null;
}

export interface TablePart {
  kind: "table";
  id: string;
  tool: string;
  columns: string[];
  rows: unknown[][];
  device_ids: (number | null)[];
  total?: number | null;
  truncated: boolean;
}

export interface ChartPart {
  kind: "chart";
  id: string;
  chart_type: "pie" | "bar" | "hbar" | "line";
  title: string;
  labels: string[];
  series: { name: string; values: number[] }[];
  unit?: string | null;
}

export type Part =
  | { kind: "text"; text: string }
  | ToolPart
  | TablePart
  | ChartPart
  | { kind: "notice"; text: string }
  | { kind: "error"; text: string };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text?: string;
  parts: Part[];
  pending?: boolean;
  /** Running token totals for this answer; updated after every model call ("usage" events), final on "done". */
  usage?: Record<string, number>;
  /** Characters of answer text streamed since the last usage event (for a live ~token estimate). */
  streamChars?: number;
  model?: string;
}

let seq = 0;
const nid = () => `m${++seq}`;

type ServerEvent = { type: string; [k: string]: unknown };

function applyEvent(msg: ChatMessage, ev: ServerEvent): ChatMessage {
  const parts = [...msg.parts];
  const last = parts[parts.length - 1];
  switch (ev.type) {
    case "text": {
      const t = String(ev.text ?? "");
      if (!t) return msg;
      if (last?.kind === "text") parts[parts.length - 1] = { kind: "text", text: last.text + t };
      else parts.push({ kind: "text", text: t });
      return { ...msg, parts, streamChars: (msg.streamChars ?? 0) + t.length };
    }
    case "usage":
      return { ...msg, usage: ev.usage as Record<string, number>, streamChars: 0 };
    case "tool_start":
      parts.push({ kind: "tool", id: String(ev.id), name: String(ev.name), status: "running" });
      break;
    case "tool_end": {
      const i = parts.findIndex((p) => p.kind === "tool" && p.id === ev.id);
      const done: ToolPart = {
        kind: "tool", id: String(ev.id), name: String(ev.name), status: ev.error ? "error" : "done",
        input: ev.input, rows: ev.rows as number | null, ms: ev.ms as number, truncated: Boolean(ev.truncated),
        error: (ev.error as string | null) ?? null,
      };
      if (i >= 0) parts[i] = done;
      else parts.push(done);
      break;
    }
    case "table":
      parts.push({ kind: "table", ...(ev as unknown as Omit<TablePart, "kind">) });
      break;
    case "chart":
      parts.push({ ...(ev as unknown as Omit<ChartPart, "kind">), kind: "chart" });
      break;
    case "notice":
      parts.push({ kind: "notice", text: String(ev.message ?? "") });
      break;
    case "error":
      parts.push({ kind: "error", text: String(ev.message ?? "Error") });
      break;
    case "done":
      return { ...msg, parts, pending: false, streamChars: 0, usage: ev.usage as Record<string, number>, model: ev.model as string | undefined };
    default:
      return msg;
  }
  return { ...msg, parts };
}

const MODEL_KEY = "pms.chat.model";

function loadModel(): string | null {
  try {
    return localStorage.getItem(MODEL_KEY);
  } catch {
    return null;
  }
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // Selected model id; null = server default. Remembered per browser.
  const [model, setModelState] = useState<string | null>(loadModel);
  const modelRef = useRef(model);
  const setModel = useCallback((m: string | null) => {
    modelRef.current = m;
    setModelState(m);
    try {
      if (m) localStorage.setItem(MODEL_KEY, m);
      else localStorage.removeItem(MODEL_KEY);
    } catch {
      /* storage unavailable */
    }
  }, []);
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(async (text: string, deviceId?: number | null) => {
    const message = text.trim();
    if (!message || abortRef.current) return;
    const user: ChatMessage = { id: nid(), role: "user", text: message, parts: [] };
    const asst: ChatMessage = { id: nid(), role: "assistant", parts: [], pending: true };
    setMessages((m) => [...m, user, asst]);
    setBusy(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const update = (ev: ServerEvent) =>
      setMessages((ms) => ms.map((m) => (m.id === asst.id ? applyEvent(m, ev) : m)));

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionRef.current, message, device_id: deviceId ?? null, model: modelRef.current }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const data = chunk.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
          if (!data) continue;
          const ev = JSON.parse(data) as ServerEvent;
          if (ev.type === "session") sessionRef.current = String(ev.session_id);
          else update(ev);
        }
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") update({ type: "notice", message: "Stopped." });
      else update({ type: "error", message: `Connection failed: ${(e as Error).message}` });
    } finally {
      setMessages((ms) => ms.map((m) => (m.id === asst.id ? { ...m, pending: false } : m)));
      abortRef.current = null;
      setBusy(false);
    }
  }, []);

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    const sid = sessionRef.current;
    sessionRef.current = null;
    setMessages([]);
    if (sid) fetch(`/api/chat/${sid}`, { method: "DELETE" }).catch(() => {});
  }, []);

  return { messages, busy, send, stop, reset, model, setModel };
}
