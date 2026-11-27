"""Claude tool-use loop with streaming.

Self-hosted loop on the Messages API (beta endpoint, for server-side refusal fallbacks).
Tools run in-process against app.queries via the shared registry.
Yields dict events that app.api.chat serializes as Server-Sent Events.
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, AsyncIterator

import anthropic
import httpx

from app.chat import openrouter, sessions
from app.chat.prompts import SYSTEM_PROMPT
from app.config import get_settings
from app.queries.models import BKK
from app.tools.registry import TOOLS, TOOLS_BY_NAME, ToolDef, ToolInputError

log = logging.getLogger("pms.chat")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
TABLE_MAX_ROWS = 100

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
  global _client
  if _client is None:
    key = get_settings().anthropic_api_key or None
    _client = anthropic.AsyncAnthropic(api_key=key) if key else anthropic.AsyncAnthropic()
  return _client


def _claude_tools() -> list[dict[str, Any]]:
  return [t.claude_tool() for t in TOOLS]


def _get_path(row: dict[str, Any], path: str) -> Any:
  cur: Any = row
  for part in path.split("."):
    if not isinstance(cur, dict):
      return None
    cur = cur.get(part)
  return cur


def _table_event(tool: ToolDef, result: dict[str, Any]) -> dict[str, Any] | None:
  if not tool.table_columns:
    return None
  key = next((k for k in ("items", "groups", "values") if isinstance(result.get(k), list)), None)
  if key is None or not result[key]:
    return None
  rows = result[key][:TABLE_MAX_ROWS]
  cols = tool.table_columns
  return {
    "type": "table",
    "tool": tool.name,
    "columns": cols,
    "rows": [[_get_path(r, c) for c in cols] for r in rows],
    "device_ids": [(r.get("device_id") if "device_id" in r else r.get("id")) if tool.name not in ("count_devices", "list_filter_values") else None for r in rows],
    "total": result.get("total"),
    "truncated": bool(result.get("truncated")) or len(result[key]) > TABLE_MAX_ROWS,
  }


async def _run_tool(block: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
  """Run one tool_use block. Returns (tool_result block, UI events)."""
  t0 = time.perf_counter()
  tool = TOOLS_BY_NAME.get(block.name)
  events: list[dict[str, Any]] = []
  if tool is None:
    content, is_error, result = f"unknown tool {block.name}", True, None
  else:
    try:
      result = await tool.run(block.input)
      content, is_error = json.dumps(result, default=str, ensure_ascii=False), False
      if "chart" in result and tool.chat_only:
        content = "Chart displayed to the user below your message. Do not describe how to view it."
    except ToolInputError as e:
      content, is_error, result = f"Error: {e}", True, None
    except Exception:
      log.exception("tool %s failed", block.name)
      content, is_error, result = "Error: internal error while querying the database (it may have timed out); try a narrower query.", True, None
  ms = int((time.perf_counter() - t0) * 1000)
  rows = None
  if isinstance(result, dict):
    for k in ("items", "groups", "values", "candidates"):
      if isinstance(result.get(k), list):
        rows = len(result[k])
        break
  events.append({
    "type": "tool_end", "id": block.id, "name": block.name, "input": block.input, "ms": ms,
    "rows": rows, "truncated": bool(result.get("truncated")) if isinstance(result, dict) else False,
    "error": content if is_error else None,
  })
  if tool is not None and tool.chat_only and isinstance(result, dict) and "chart" in result:
    c = result["chart"]
    events.append({"type": "chart", "id": block.id, "chart_type": c["type"], "title": c["title"],
                   "labels": c["labels"], "series": c["series"], "unit": c.get("unit")})
  if tool is not None and isinstance(result, dict):
    tbl = _table_event(tool, result)
    if tbl:
      tbl["id"] = block.id
      events.append(tbl)
  tr: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id, "content": content}
  if is_error:
    tr["is_error"] = True
  return tr, events


def _user_turn(message: str, device_id: int | None) -> dict[str, Any]:
  now = datetime.now(BKK).strftime("%Y-%m-%d %H:%M")
  ctx = f"[context: current time {now} Asia/Bangkok"
  if device_id is not None:
    ctx += f"; the user is viewing device id {device_id}"
  ctx += "]"
  if get_settings().llm_provider == "openrouter":
    return openrouter.user_message(f"{ctx}\n\n{message}")
  return {"role": "user", "content": [{"type": "text", "text": f"{ctx}\n\n{message}"}]}


def _request_kwargs(model: str) -> dict[str, Any]:
  s = get_settings()
  kw: dict[str, Any] = {
    "model": model,
    "max_tokens": s.chat_max_tokens,
    "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
    "tools": _claude_tools(),
    "thinking": {"type": "adaptive"},
    "output_config": {"effort": s.chat_effort},
    "cache_control": {"type": "ephemeral"},
  }
  if s.chat_fallbacks and s.chat_fallbacks != "off":
    kw["betas"] = [FALLBACK_BETA]
    kw["fallbacks"] = s.chat_fallbacks
  return kw


_ANTHROPIC_NAMES = {"claude-opus-5-5": "Claude Opus 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-haiku-5-5": "Claude Haiku 5.5"}


async def list_models() -> dict[str, Any]:
  s = get_settings()
  cat = await openrouter.model_catalog() if s.llm_provider == "openrouter" else {}
  out = []
  for mid in s.chat_model_list:
    m = cat.get(mid) or {}
    p = m.get("pricing") or {}
    out.append({
      "id": mid,
      "name": m.get("name") or _ANTHROPIC_NAMES.get(mid) or mid,
      # USD per million tokens, when the provider publishes it
      "input_per_mtok": round(float(p["prompt"]) * 1e6, 3) if p.get("prompt") else None,
      "output_per_mtok": round(float(p["completion"]) * 1e6, 3) if p.get("completion") else None,
    })
  return {"provider": s.llm_provider, "default": s.active_chat_model, "models": out}


def _forget_reasoning(sess: sessions.Session) -> None:
  """Thinking/reasoning from one model is not valid input for another: drop it on a model switch."""
  if get_settings().llm_provider == "openrouter":
    openrouter.strip_reasoning(sess.messages)
    return
  for m in sess.messages:
    if m["role"] == "assistant" and isinstance(m["content"], list):
      m["content"] = [b for b in m["content"] if getattr(b, "type", None) not in ("thinking", "redacted_thinking")]


async def run_turn(session_id: str | None, message: str, device_id: int | None = None, model: str | None = None) -> AsyncIterator[dict[str, Any]]:
  s = get_settings()
  sess = sessions.get_or_create(session_id)
  yield {"type": "session", "session_id": sess.id}
  model = model or s.active_chat_model
  if model not in s.chat_model_list:
    yield {"type": "error", "message": f"Model {model} is not available here."}
    yield {"type": "done", "usage": {}, "model": model, "provider": s.llm_provider}
    return
  if sess.lock.locked():
    yield {"type": "error", "message": "This conversation is still answering the previous message."}
    return
  async with sess.lock:
    if sess.model and sess.model != model:
      _forget_reasoning(sess)
    start_len = len(sess.messages)
    sess.messages.append(_user_turn(message, device_id))
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "calls": 0}
    ok = False
    try:
      async with asyncio.timeout(s.chat_turn_timeout_s):
        events = openrouter.loop(sess.messages, usage, _run_tool, model) if s.llm_provider == "openrouter" else _loop(sess, usage, model)
        async for ev in events:
          yield ev
      ok = True
      sess.model = model
    except TimeoutError:
      yield {"type": "error", "message": f"The answer took longer than {s.chat_turn_timeout_s}s and was stopped. Try a narrower question."}
    except openrouter.ProviderError as e:
      yield {"type": "error", "message": str(e)}
    except (httpx.ProxyError, httpx.ConnectError, httpx.ConnectTimeout):
      yield {"type": "error", "message": "Cannot reach the LLM provider through the network/proxy. Please retry; if it persists, check OPENROUTER_PROXY."}
    except anthropic.AuthenticationError:
      yield {"type": "error", "message": "Claude API authentication failed. Set ANTHROPIC_API_KEY in backend/.env."}
    except anthropic.RateLimitError:
      yield {"type": "error", "message": "Claude API rate limit reached. Please retry in a moment."}
    except anthropic.APIStatusError as e:
      log.warning("Claude API error %s: %s", e.status_code, e.message)
      yield {"type": "error", "message": f"Claude API error ({e.status_code}). Please retry."}
    except anthropic.APIConnectionError:
      yield {"type": "error", "message": "Cannot reach the Claude API (network/proxy). Check outbound HTTPS to api.anthropic.com."}
    except anthropic.AnthropicError as e:
      yield {"type": "error", "message": f"Claude client error: {e}"}
    except TypeError as e:
      if "authentication method" not in str(e):
        log.exception("chat turn failed")
        yield {"type": "error", "message": "Internal error while answering."}
      else:
        yield {"type": "error", "message": "Chat is not configured: set ANTHROPIC_API_KEY in backend/.env and restart the backend."}
    except Exception:
      log.exception("chat turn failed")
      yield {"type": "error", "message": "Internal error while answering."}
    finally:
      if not ok:
        # Keep history consistent: drop the partial turn so the next request is well-formed.
        del sess.messages[start_len:]
    yield {"type": "done", "usage": usage, "model": model, "provider": s.llm_provider}


async def _loop(sess: sessions.Session, usage: dict[str, int], model: str) -> AsyncIterator[dict[str, Any]]:
  s = get_settings()
  kwargs = _request_kwargs(model)
  json_retries = 0
  for step in range(s.chat_max_iterations):
    try:
      async with client().beta.messages.stream(messages=sess.messages, **kwargs) as stream:
        async for ev in stream:
          if ev.type == "text":
            yield {"type": "text", "text": ev.text}
          elif ev.type == "content_block_start" and getattr(ev.content_block, "type", None) == "tool_use":
            yield {"type": "tool_start", "id": ev.content_block.id, "name": ev.content_block.name}
        final = await stream.get_final_message()
      json_retries = 0
    except ValueError:
      # Tool input JSON the SDK could not parse at all: re-issue this step (bounded).
      json_retries += 1
      if json_retries > 2:
        raise anthropic.AnthropicError("model produced unparseable tool input repeatedly")
      yield {"type": "notice", "message": "retrying…"}
      continue

    u = final.usage
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
      usage[k] += getattr(u, k, 0) or 0
    usage["calls"] = usage.get("calls", 0) + 1
    # Running totals for the live token counter in the UI (one event per model call).
    yield {"type": "usage", "usage": dict(usage)}

    sess.messages.append({"role": "assistant", "content": final.content})

    if final.stop_reason == "pause_turn":
      continue
    if final.stop_reason == "refusal":
      yield {"type": "notice", "message": "The model declined to answer this request."}
      return
    tool_uses = [b for b in final.content if b.type == "tool_use"]
    if not tool_uses:
      if final.stop_reason == "max_tokens":
        yield {"type": "notice", "message": "The answer was cut off (length limit)."}
      return
    if final.stop_reason == "max_tokens":
      # A truncated tool input parses as a partial object; never run it.
      sess.messages.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": b.id, "is_error": True, "content": "Error: tool input was truncated"} for b in tool_uses
      ]})
      continue

    results = await asyncio.gather(*(_run_tool(b) for b in tool_uses))
    for _, evs in results:
      for e in evs:
        yield e
    sess.messages.append({"role": "user", "content": [tr for tr, _ in results]})

  # Iteration cap reached: ask for a final answer without further tool calls.
  note = {"type": "text", "text": "Tool-call limit reached for this question. Answer now with what you have, and say what is missing."}
  last = sess.messages[-1]
  if last["role"] == "user":
    last["content"] = [*last["content"], note]
  else:
    sess.messages.append({"role": "user", "content": [note]})
  async with client().beta.messages.stream(messages=sess.messages, **{**kwargs, "tool_choice": {"type": "none"}}) as stream:
    async for ev in stream:
      if ev.type == "text":
        yield {"type": "text", "text": ev.text}
    final = await stream.get_final_message()
  sess.messages.append({"role": "assistant", "content": final.content})
