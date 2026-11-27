"""OpenRouter provider tests with a mocked HTTP transport (no network, no DB)."""
import json

import httpx
import pytest

from app.chat import openrouter, orchestrator
from app.config import get_settings
from app.tools import registry


def sse(chunks: list[dict]) -> bytes:
  out = ": OPENROUTER PROCESSING\n\n"
  for c in chunks:
    out += f"data: {json.dumps(c)}\n\n"
  return (out + "data: [DONE]\n\n").encode()


@pytest.fixture
def setup(monkeypatch):
  s = get_settings()
  monkeypatch.setattr(s, "llm_provider", "openrouter")
  monkeypatch.setattr(s, "openrouter_api_key", "test-key")
  requests: list[dict] = []
  script: list[bytes] = []

  def handler(req: httpx.Request) -> httpx.Response:
    requests.append(json.loads(req.content))
    assert req.headers["authorization"] == "Bearer test-key"
    return httpx.Response(200, content=script.pop(0), headers={"content-type": "text/event-stream"})

  monkeypatch.setattr(openrouter, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))

  async def fake_handler(a):
    return {"items": [{"id": 7, "name": "DEV7", "ip": "10.0.0.7"}], "total": 1, "truncated": False}
  monkeypatch.setattr(registry.TOOLS_BY_NAME["search_devices"], "handler", fake_handler)
  return requests, script


async def test_tool_round_trip(setup):
  requests, script = setup
  script.append(sse([
    {"choices": [{"delta": {"content": "Checking."}}]},
    {"choices": [{"delta": {"reasoning_details": [{"type": "reasoning.text", "index": 0, "text": "think "}]}}]},
    {"choices": [{"delta": {"reasoning_details": [{"type": "reasoning.text", "index": 0, "text": "more", "signature": "sig"}]}}]},
    {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "type": "function", "function": {"name": "search_devices", "arguments": ""}}]}}]},
    {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"q\": \"DEV\","}}]}}]},
    {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": " \"limit\": 5}"}}]}, "finish_reason": "tool_calls"}]},
    {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 80}, "cost": 0.001}},
  ]))
  script.append(sse([
    {"choices": [{"delta": {"content": "Found DEV7."}, "finish_reason": "stop"}]},
    {"choices": [], "usage": {"prompt_tokens": 150, "completion_tokens": 10, "cost": 0.0005}},
  ]))
  evs = [e async for e in orchestrator.run_turn(None, "find DEV")]
  types = [e["type"] for e in evs]
  assert types[0] == "session" and types[-1] == "done"
  assert {"tool_start", "tool_end", "table"} <= set(types)
  assert "".join(e["text"] for e in evs if e["type"] == "text") == "Checking.Found DEV7."
  done = evs[-1]
  assert done["provider"] == "openrouter" and done["usage"]["input_tokens"] == 250 and done["usage"]["cache_read_input_tokens"] == 80
  assert done["usage"]["cost_usd"] == pytest.approx(0.0015)
  # second request carries assistant tool_calls (+ merged reasoning) and a tool message
  msgs = requests[1]["messages"]
  assert msgs[0]["role"] == "system"
  asst = msgs[-2]
  assert asst["role"] == "assistant" and asst["tool_calls"][0]["function"]["arguments"] == '{"q": "DEV", "limit": 5}'
  assert asst["reasoning_details"] == [{"type": "reasoning.text", "index": 0, "text": "think more", "signature": "sig"}]
  assert msgs[-1]["role"] == "tool" and msgs[-1]["tool_call_id"] == "c1" and "DEV7" in msgs[-1]["content"]
  assert requests[0]["model"] == get_settings().openrouter_model and requests[0]["stream"] is True


async def test_bad_json_args_become_error_result(setup):
  requests, script = setup
  script.append(sse([
    {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "search_devices", "arguments": "{not json"}}]}, "finish_reason": "tool_calls"}]},
  ]))
  script.append(sse([{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}]))
  evs = [e async for e in orchestrator.run_turn(None, "x")]
  end = next(e for e in evs if e["type"] == "tool_end")
  assert end["error"] and "not valid JSON" in end["error"]
  assert requests[1]["messages"][-1]["role"] == "tool"


async def test_http_error_is_reported_and_rolled_back(setup, monkeypatch):
  monkeypatch.setattr(openrouter, "_client", httpx.AsyncClient(transport=httpx.MockTransport(
    lambda req: httpx.Response(401, json={"error": {"message": "No auth credentials found", "code": 401}}))))
  sid = "or-401"
  evs = [e async for e in orchestrator.run_turn(sid, "x")]
  err = next(e for e in evs if e["type"] == "error")
  assert "authentication failed" in err["message"]
  from app.chat import sessions
  assert sessions.get_or_create(sid).messages == []


async def test_model_switch_uses_chosen_model_and_drops_reasoning(setup):
  requests, script = setup
  script.append(sse([
    {"choices": [{"delta": {"reasoning_details": [{"type": "reasoning.text", "index": 0, "text": "hmm"}]}}]},
    {"choices": [{"delta": {"content": "first"}, "finish_reason": "stop"}]},
  ]))
  script.append(sse([{"choices": [{"delta": {"content": "second"}, "finish_reason": "stop"}]}]))
  first = [e async for e in orchestrator.run_turn(None, "q1")]
  sid = first[0]["session_id"]
  other = get_settings().chat_model_list[1]
  second = [e async for e in orchestrator.run_turn(sid, "q2", model=other)]
  assert requests[0]["model"] == get_settings().openrouter_model
  assert requests[1]["model"] == other and second[-1]["model"] == other
  assert all("reasoning_details" not in m for m in requests[1]["messages"])


async def test_unknown_model_rejected(setup):
  requests, _ = setup
  evs = [e async for e in orchestrator.run_turn(None, "q", model="evil/model")]
  assert any(e["type"] == "error" for e in evs) and not requests
