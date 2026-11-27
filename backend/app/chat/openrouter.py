"""OpenRouter provider: OpenAI-compatible /chat/completions with streaming tool calls.

Used when LLM_PROVIDER=openrouter. Emits the same UI events as the Anthropic loop, and runs
tools through the same registry, so the frontend and the tools don't change.
Conversation history is kept in OpenAI message format (system/user/assistant/tool).
"""
import asyncio
import json
import logging
import time
from types import SimpleNamespace as NS
from typing import Any, AsyncIterator

import httpx

from app.chat.prompts import SYSTEM_PROMPT
from app.config import get_settings
from app.tools.registry import TOOLS

log = logging.getLogger("pms.chat.openrouter")


class ProviderError(Exception):
  """User-presentable provider failure."""


_client: httpx.AsyncClient | None = None


def http() -> httpx.AsyncClient:
  global _client
  if _client is None:
    proxy = get_settings().openrouter_proxy or None  # only this client uses the proxy
    _client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0), proxy=proxy)
  return _client


def _tools() -> list[dict[str, Any]]:
  return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema()}} for t in TOOLS]


def user_message(text: str) -> dict[str, Any]:
  return {"role": "user", "content": text}


def _system() -> dict[str, Any]:
  # cache_control is passed through by OpenRouter to Anthropic models (prompt caching); ignored elsewhere.
  return {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]}


def _merge_reasoning(acc: dict[int, dict[str, Any]], items: list[dict[str, Any]]) -> None:
  """Accumulate streamed reasoning_details fragments (needed to continue a tool-use turn with thinking)."""
  for it in items:
    idx = it.get("index", len(acc))
    cur = acc.setdefault(idx, {})
    for k, v in it.items():
      if k in ("text", "summary") and isinstance(v, str):
        cur[k] = cur.get(k, "") + v
      elif v is not None:
        cur[k] = v


def _error_message(status: int, body: str) -> str:
  try:
    msg = json.loads(body).get("error", {}).get("message") or body
  except Exception:
    msg = body
  msg = str(msg)[:300]
  if status == 401:
    return "OpenRouter authentication failed. Check OPENROUTER_API_KEY in backend/.env."
  if status == 402:
    return "OpenRouter account has insufficient credits for this request."
  if status == 429:
    return "OpenRouter rate limit reached. Please retry in a moment."
  if status == 404:
    return f"OpenRouter model not available: {msg}"
  return f"OpenRouter error ({status}): {msg}"


async def _stream_step(messages: list[dict[str, Any]], usage: dict[str, Any], model: str, final_answer: bool = False) -> AsyncIterator[dict[str, Any]]:
  """One completion request. Yields UI events, and finally {"type": "_step", ...} with the assembled turn."""
  s = get_settings()
  body: dict[str, Any] = {
    "model": model,
    "messages": [_system(), *messages],
    "tools": _tools(),
    "tool_choice": "none" if final_answer else "auto",
    "stream": True,
    "max_tokens": s.chat_max_tokens,
    "reasoning": {"effort": s.chat_effort},
    "stream_options": {"include_usage": True},
  }
  headers = {
    "Authorization": f"Bearer {s.openrouter_api_key}",
    "Content-Type": "application/json",
    "X-Title": "PMS Online prototype",
  }
  text_parts: list[str] = []
  calls: dict[int, dict[str, Any]] = {}
  reasoning: dict[int, dict[str, Any]] = {}
  finish: str | None = None

  # Retry connection-level failures (flaky proxy) before anything has streamed; never retry mid-stream.
  for attempt in range(3):
    try:
      req = http().build_request("POST", f"{s.openrouter_base_url}/chat/completions", headers=headers, json=body)
      resp = await http().send(req, stream=True)
      break
    except (httpx.ProxyError, httpx.ConnectError, httpx.ConnectTimeout) as e:
      if attempt == 2:
        raise
      log.warning("OpenRouter connect failed (%s), retrying", e)
      await asyncio.sleep(1 + attempt)
  try:
    if resp.status_code != 200:
      raise ProviderError(_error_message(resp.status_code, (await resp.aread()).decode(errors="replace")))
    async for line in resp.aiter_lines():
      if not line or line.startswith(":"):
        continue  # keep-alive comments
      if not line.startswith("data:"):
        continue
      data = line[5:].strip()
      if data == "[DONE]":
        break
      chunk = json.loads(data)
      if chunk.get("error"):
        raise ProviderError(_error_message(int(chunk["error"].get("code") or 500), json.dumps(chunk)))
      if chunk.get("usage"):
        u = chunk["usage"]
        usage["input_tokens"] += u.get("prompt_tokens") or 0
        usage["output_tokens"] += u.get("completion_tokens") or 0
        usage["cache_read_input_tokens"] += (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        usage["cost_usd"] = round(usage.get("cost_usd", 0.0) + float(u.get("cost") or 0.0), 6)
        usage["calls"] = usage.get("calls", 0) + 1
        # Running totals for the live token counter in the UI (one event per model call).
        yield {"type": "usage", "usage": dict(usage)}
      for ch in chunk.get("choices") or []:
        delta = ch.get("delta") or {}
        if delta.get("content"):
          text_parts.append(delta["content"])
          yield {"type": "text", "text": delta["content"]}
        if delta.get("reasoning_details"):
          _merge_reasoning(reasoning, delta["reasoning_details"])
        for tc in delta.get("tool_calls") or []:
          idx = tc.get("index", 0)
          cur = calls.get(idx)
          if cur is None:
            cur = calls[idx] = {"id": tc.get("id") or f"call_{idx}", "name": "", "arguments": ""}
          fn = tc.get("function") or {}
          if tc.get("id"):
            cur["id"] = tc["id"]
          if fn.get("name"):
            started = bool(cur["name"])
            cur["name"] += fn["name"]
            if not started:
              yield {"type": "tool_start", "id": cur["id"], "name": cur["name"]}
          if fn.get("arguments"):
            cur["arguments"] += fn["arguments"]
        if ch.get("finish_reason"):
          finish = ch["finish_reason"]
  finally:
    await resp.aclose()

  assistant: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
  if calls:
    assistant["tool_calls"] = [
      {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
      for _, c in sorted(calls.items())
    ]
  if reasoning:
    assistant["reasoning_details"] = [reasoning[k] for k in sorted(reasoning)]
  yield {"type": "_step", "assistant": assistant, "finish": finish, "calls": [c for _, c in sorted(calls.items())]}


def strip_reasoning(messages: list[dict[str, Any]]) -> None:
  """Drop provider-specific reasoning from history (needed when the conversation switches model)."""
  for m in messages:
    m.pop("reasoning_details", None)


_models_cache: tuple[float, dict[str, dict[str, Any]]] | None = None


async def model_catalog() -> dict[str, dict[str, Any]]:
  """OpenRouter model metadata by id (cached 1h). Empty dict if unreachable."""
  global _models_cache
  if _models_cache and time.monotonic() - _models_cache[0] < 3600:
    return _models_cache[1]
  try:
    r = await http().get(f"{get_settings().openrouter_base_url}/models", timeout=15.0)
    r.raise_for_status()
    cat = {m["id"]: m for m in r.json().get("data", [])}
  except Exception as e:
    log.warning("could not load OpenRouter model list: %s", e)
    return _models_cache[1] if _models_cache else {}
  _models_cache = (time.monotonic(), cat)
  return cat


async def loop(messages: list[dict[str, Any]], usage: dict[str, Any], run_tool: Any, model: str) -> AsyncIterator[dict[str, Any]]:
  s = get_settings()
  for _ in range(s.chat_max_iterations):
    step: dict[str, Any] | None = None
    async for ev in _stream_step(messages, usage, model):
      if ev["type"] == "_step":
        step = ev
      else:
        yield ev
    assert step is not None
    messages.append(step["assistant"])
    calls = step["calls"]
    if not calls:
      if step["finish"] == "length":
        yield {"type": "notice", "message": "The answer was cut off (length limit)."}
      return

    blocks = []
    pre_errors: dict[str, str] = {}
    for c in calls:
      try:
        args = json.loads(c["arguments"] or "{}")
      except json.JSONDecodeError:
        args = None
      if step["finish"] == "length" or not isinstance(args, dict):
        pre_errors[c["id"]] = "Error: tool input was truncated or not valid JSON"
        args = {}
      blocks.append(NS(id=c["id"], name=c["name"], input=args))

    async def one(b: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
      if b.id in pre_errors:
        return {"tool_use_id": b.id, "content": pre_errors[b.id], "is_error": True}, [
          {"type": "tool_end", "id": b.id, "name": b.name, "input": b.input, "ms": 0, "rows": None, "truncated": False, "error": pre_errors[b.id]}]
      return await run_tool(b)

    results = await asyncio.gather(*(one(b) for b in blocks))
    for tr, evs in results:
      for e in evs:
        yield e
      messages.append({"role": "tool", "tool_call_id": tr["tool_use_id"], "content": tr["content"]})

  # Iteration cap reached: one more call with tools disabled to force a final answer.
  messages.append({"role": "user", "content": "Tool-call limit reached for this question. Answer now with what you have, and say what is missing."})
  async for ev in _stream_step(messages, usage, model, final_answer=True):
    if ev["type"] == "_step":
      messages.append(ev["assistant"])
    else:
      yield ev
