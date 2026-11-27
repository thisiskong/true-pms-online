from app.tools import fiber_tools as ft
from app.tools.registry import MCP_TOOLS, TOOLS_BY_NAME, ToolInputError


def test_explain_redistributes_missing_error_and_caps():
  o = {"s_power": 0.2, "s_excess": 0.0, "s_error": None, "s_stability": 1.0, "rx_med": -28.4,
       "vendor": "GCOM", "bip_days": None, "bip_obs": 0}
  e = ft.explain(o)
  assert e["sub_scores"]["error"]["effective_weight"] == 0.0
  assert e["sub_scores"]["power"]["effective_weight"] == 0.5
  assert any("capped at 3" in c for c in e["caps_applied"])
  assert any("no BIP" in n for n in e["notes"])


def test_explain_strictest_rx_cap_and_bip_cap():
  e = ft.explain({"s_power": 0.0, "s_excess": 0.0, "s_error": 0.0, "s_stability": 0.0, "rx_med": -31.0,
                  "bip_days": 7, "bip_obs": 7})
  assert e["caps_applied"][0].endswith("capped at 1")
  assert any("every observed day" in c for c in e["caps_applied"])


def test_explain_no_bip_cap_for_some_error_days_or_too_few_days():
  base = {"s_power": 1.0, "s_excess": 1.0, "s_error": 0.5, "s_stability": 1.0, "rx_med": -20.0}
  assert ft.explain({**base, "bip_days": 1, "bip_obs": 7})["caps_applied"] == []
  assert ft.explain({**base, "bip_days": 2, "bip_obs": 2})["caps_applied"] == []


async def test_fiber_tools_registered_and_validate():
  names = {"fiber_overview", "list_fiber_suspects", "fiber_device_tree", "list_fiber_onus", "get_onu_fiber_score"}
  assert names <= {t.name for t in MCP_TOOLS}
  for bad in ({"date": "nope"}, {"extra": 1}):
    try:
      await TOOLS_BY_NAME["fiber_overview"].run(bad)
      raise AssertionError("expected ToolInputError")
    except ToolInputError:
      pass
  try:
    await TOOLS_BY_NAME["fiber_device_tree"].run({})
    raise AssertionError("expected ToolInputError")
  except ToolInputError as e:
    assert "device_id or device" in str(e)
