"""Access-id lookup: input handling (no DB) and an end-to-end lookup against the real DB (skipped if unreachable)."""
import pytest

from app import db
from app.queries import access
from app.tools.registry import MCP_TOOLS, TOOLS_BY_NAME, ToolInputError


def test_normalize_strips_spaces_and_rejects_junk():
  assert access.normalize(" 9605 163 336 ") == "9605163336"
  for bad in ("", "12", "96051'; select 1", "a" * 51):
    with pytest.raises(ValueError):
      access.normalize(bad)


async def test_tool_registered_and_validates():
  assert "find_by_accessid" in {t.name for t in MCP_TOOLS}
  tool = TOOLS_BY_NAME["find_by_accessid"]
  for bad in ({}, {"accessid": "96"}, {"accessid": "9605163336", "extra": 1}, {"accessid": "x' or 1=1 --"}):
    with pytest.raises(ToolInputError):
      await tool.run(bad)


@pytest.fixture
async def pool():
  try:
    await db.open_pool()
  except Exception as e:  # pragma: no cover
    pytest.skip(f"database unreachable: {e}")
  yield
  await db.close_pool()


async def test_lookup_end_to_end(pool):
  acc = await db.fetchval("SELECT accessid FROM odn_onu WHERE accessid IS NOT NULL LIMIT 1")
  r = await TOOLS_BY_NAME["find_by_accessid"].run({"accessid": acc, "tickets": 3})
  assert r["accessid"] == acc
  assert r["onu"]["device_name"] and r["onu"]["ponport"] and r["onu"]["ontid"]
  assert r["device"]["name"] == r["onu"]["device_name"]
  assert "data_to" in r["tickets"] and len(r["tickets"]["items"]) <= 3
  with pytest.raises(ToolInputError):
    await TOOLS_BY_NAME["find_by_accessid"].run({"accessid": "0000000000000"})


async def test_unscored_reason_explains_missing_onu(pool):
  from app.queries import fiber
  row = await db.fetchrow("SELECT device, ponport FROM odn_onu LIMIT 1")
  try:
    msg = await fiber.unscored_reason(None, row["device"], row["ponport"], "99999")
  except fiber.RunNotFound:
    pytest.skip("no fiber-score runs available")
  assert "not in the ODN inventory" in msg and row["ponport"] in msg
