"""Chat orchestrator tests with a fake Anthropic streaming client (no network, no DB)."""
from types import SimpleNamespace as NS
from typing import Any

import pytest

from app.chat import orchestrator, sessions
from app.tools import registry


class FakeStream:
  def __init__(self, events: list[Any], final: Any):
    self.events, self.final = events, final

  async def __aenter__(self):
    return self

  async def __aexit__(self, *a):
    return False

  def __aiter__(self):
    async def gen():
      for e in self.events:
        yield e
    return gen()

  async def get_final_message(self):
    return self.final


class FakeClient:
  def __init__(self, script: list[FakeStream]):
    self.script = script
    self.calls: list[dict[str, Any]] = []
    self.beta = NS(messages=NS(stream=self._stream))

  def _stream(self, **kw):
    self.calls.append({**kw, "messages": list(kw["messages"])})
    return self.script.pop(0)


def usage():
  return NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)


def tool_use(id_: str, name: str, inp: dict) -> Any:
  return NS(type="tool_use", id=id_, name=name, input=inp)


def text(t: str) -> Any:
  return NS(type="text", text=t)


@pytest.fixture(autouse=True)
def anthropic_provider(monkeypatch):
  from app.config import get_settings
  monkeypatch.setattr(get_settings(), "llm_provider", "anthropic")


@pytest.fixture
def fake(monkeypatch):
  def install(script):
    c = FakeClient(script)
    monkeypatch.setattr(orchestrator, "client", lambda: c)
    return c
  return install


@pytest.fixture
def fake_tool(monkeypatch):
  async def handler(a):
    return {"items": [{"id": 1, "name": "DEV1", "ip": "10.0.0.1"}], "total": 1, "truncated": False}
  t = registry.TOOLS_BY_NAME["search_devices"]
  monkeypatch.setattr(t, "handler", handler)
  return t


async def collect(gen):
  return [e async for e in gen]


async def test_tool_round_trip(fake, fake_tool):
  tu = tool_use("tu1", "search_devices", {"q": "DEV", "limit": 5})
  c = fake([
    FakeStream(
      [NS(type="content_block_start", content_block=tu), NS(type="text", text="")],
      NS(content=[tu], stop_reason="tool_use", usage=usage()),
    ),
    FakeStream(
      [NS(type="text", text="Found DEV1.")],
      NS(content=[text("Found DEV1.")], stop_reason="end_turn", usage=usage()),
    ),
  ])
  evs = await collect(orchestrator.run_turn(None, "find DEV"))
  types = [e["type"] for e in evs]
  assert types[0] == "session"
  assert "tool_start" in types and "tool_end" in types and "table" in types
  assert types[-1] == "done" and evs[-1]["usage"]["input_tokens"] == 20
  tbl = next(e for e in evs if e["type"] == "table")
  assert tbl["columns"][:3] == ["id", "name", "ip"] and tbl["rows"][0][1] == "DEV1"
  # second request carries assistant tool_use + user tool_result, all results in ONE user message
  second = c.calls[1]["messages"]
  assert second[-2]["role"] == "assistant" and second[-1]["role"] == "user"
  assert second[-1]["content"][0]["type"] == "tool_result" and second[-1]["content"][0]["tool_use_id"] == "tu1"
  # request shape
  kw = c.calls[0]
  assert kw["model"] == "claude-opus-5-5" and kw["thinking"] == {"type": "adaptive"}
  assert "tool_choice" not in kw and kw["system"][0]["cache_control"] == {"type": "ephemeral"}
  sid = evs[0]["session_id"]
  assert len(sessions.get_or_create(sid).messages) == 4


async def test_invalid_tool_input_is_error_result(fake, fake_tool):
  tu = tool_use("tu1", "search_devices", {"limit": 999, "bogus": 1})
  c = fake([
    FakeStream([], NS(content=[tu], stop_reason="tool_use", usage=usage())),
    FakeStream([], NS(content=[text("sorry")], stop_reason="end_turn", usage=usage())),
  ])
  evs = await collect(orchestrator.run_turn(None, "x"))
  end = next(e for e in evs if e["type"] == "tool_end")
  assert end["error"] and "invalid input" in end["error"]
  tr = c.calls[1]["messages"][-1]["content"][0]
  assert tr["is_error"] is True


async def test_refusal_stops(fake):
  fake([FakeStream([], NS(content=[], stop_reason="refusal", usage=usage()))])
  evs = await collect(orchestrator.run_turn(None, "x"))
  assert any(e["type"] == "notice" for e in evs) and evs[-1]["type"] == "done"


async def test_failed_turn_rolls_back_history(fake, monkeypatch):
  class Boom(FakeStream):
    async def __aenter__(self):
      raise RuntimeError("boom")
  fake([Boom([], None)])
  sid = "rollback-test"
  evs = await collect(orchestrator.run_turn(sid, "x"))
  assert any(e["type"] == "error" for e in evs)
  assert sessions.get_or_create(sid).messages == []


def test_bound_trims_large_results():
  out = registry._bound({"items": [{"x": "y" * 500} for _ in range(200)], "total": 200})
  import json
  assert len(json.dumps(out)) <= registry.MAX_RESULT_BYTES and out["truncated"] is True


def test_claude_tool_schemas():
  for t in registry.TOOLS:
    ct = t.claude_tool()
    assert ct["input_schema"]["type"] == "object"
    assert ct["input_schema"].get("additionalProperties") is False
    assert "title" not in ct["input_schema"]


async def test_show_chart_tool_validates_and_is_chat_only():
  from app.tools.registry import MCP_TOOLS, TOOLS_BY_NAME, ToolInputError
  t = TOOLS_BY_NAME["show_chart"]
  out = await t.run({"type": "pie", "title": "OLT by vendor", "labels": ["Huawei", "ZTE"], "series": [{"name": "OLTs", "values": [10, 5]}]})
  assert out["chart"]["labels"] == ["Huawei", "ZTE"]
  with pytest.raises(ToolInputError):
    await t.run({"type": "bar", "title": "x", "labels": ["a", "b"], "series": [{"name": "s", "values": [1]}]})
  with pytest.raises(ToolInputError):
    await t.run({"type": "pie", "title": "x", "labels": ["a"], "series": [{"name": "s", "values": [1]}, {"name": "t", "values": [2]}]})
  assert "show_chart" not in {m.name for m in MCP_TOOLS}


async def test_show_chart_emits_chart_event():
  from types import SimpleNamespace
  from app.chat.orchestrator import _run_tool
  tr, evs = await _run_tool(SimpleNamespace(id="c1", name="show_chart", input={
    "type": "bar", "title": "t", "labels": ["a"], "series": [{"name": "s", "values": [3]}]}))
  chart = next(e for e in evs if e["type"] == "chart")
  assert chart["id"] == "c1" and chart["series"][0]["values"] == [3]
  assert "displayed" in tr["content"] and not tr.get("is_error")
