"""
Classify tickets using Claude API.

Workflow:
  1. Read tickets.json
  2. Extract distinct (faulttype, subcategory, faultcause) combos
  3. Send combos to Claude in batches (with prompt caching)
  4. Write category_mapping.json  -- combo -> English categories
  5. Write tickets_classified.json -- all tickets with category fields added

Usage:
  uv run python classify_tickets.py

.env keys:
  ANTHROPIC_API_KEY
  INPUT_FILE   -- default: tickets.json
  OUTPUT_FILE  -- default: tickets_classified.json
  MAPPING_FILE -- default: category_mapping.json
  BATCH_SIZE   -- combos per Claude call, default: 50
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

BATCH_SIZE = int(os.getenv("BATCH_SIZE", 50))

SYSTEM_PROMPT = """\
You are a telecom network operations analyst. You will receive a list of customer fault ticket \
classifications (originally in Thai) and return normalized English categories for each one.

For each item return a JSON object with exactly these fields:
- category: top-level English category (pick from the list below or add a new one if truly different)
- subcategory_en: more specific English subcategory (2-5 words)
- severity: "low" | "medium" | "high"
- is_network_fault: true if this is a network/infrastructure fault, false if billing/admin/CPE

Standard categories (use these when applicable):
- Optical Signal Issue
- ONU Offline / Reboot
- Slow Speed / Throughput
- Installation / New Service
- CPE / Router Issue
- Billing / Account
- Provisioning / Configuration
- Splitter / Passive Infrastructure
- Unknown / Other

Return ONLY a JSON array, one object per input item, in the same order. No extra text.\
"""


def _make_combo_key(faulttype: str | None, subcategory: str | None, faultcause: str | None) -> str:
  return "|||".join([
    (faulttype   or "").strip(),
    (subcategory or "").strip(),
    (faultcause  or "").strip(),
  ])


def _classify_batch(client: anthropic.Anthropic, combos: list[dict]) -> list[dict]:
  """Send one batch of combos to Claude and return classification results."""
  items_text = "\n".join(
    f'{i+1}. faulttype="{c["faulttype"]}" subcategory="{c["subcategory"]}" faultcause="{c["faultcause"]}"'
    for i, c in enumerate(combos)
  )

  response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=4096,
    system=[
      {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
      }
    ],
    messages=[
      {
        "role": "user",
        "content": f"Classify these {len(combos)} fault ticket types:\n\n{items_text}",
      }
    ],
  )

  text = response.content[0].text.strip()
  # strip markdown code fences if present
  if text.startswith("```"):
    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

  results = json.loads(text)
  return results


def classify(
  input_file: str = "tickets.jsonl",
  output_file: str = "tickets_classified.jsonl",
  mapping_file: str = "category_mapping.json",
) -> None:
  base = Path(__file__).parent
  in_path      = base / os.getenv("INPUT_FILE",   input_file)
  out_path     = base / os.getenv("OUTPUT_FILE",  output_file)
  mapping_path = base / os.getenv("MAPPING_FILE", mapping_file)

  if not in_path.exists():
    print(f"ERROR: {in_path} not found. Run load_tickets.py first.")
    return

  api_key = os.getenv("ANTHROPIC_API_KEY")
  if not api_key:
    print("ERROR: ANTHROPIC_API_KEY not set in .env")
    return

  print(f"Reading {in_path} ...")
  with open(in_path, encoding="utf-8") as f:
    tickets = [json.loads(line) for line in f if line.strip()]
  print(f"  {len(tickets):,} tickets loaded")

  # extract distinct combos
  seen: dict[str, dict] = {}
  for t in tickets:
    key = _make_combo_key(t.get("faulttype"), t.get("subcategory"), t.get("faultcause"))
    if key not in seen:
      seen[key] = {
        "faulttype":   (t.get("faulttype")   or "").strip(),
        "subcategory": (t.get("subcategory")  or "").strip(),
        "faultcause":  (t.get("faultcause")   or "").strip(),
      }

  combos = list(seen.values())
  keys   = list(seen.keys())
  print(f"  {len(combos)} distinct (faulttype, subcategory, faultcause) combos")

  # classify in batches
  client  = anthropic.Anthropic(api_key=api_key)
  mapping: dict[str, dict] = {}

  batches = [combos[i:i+BATCH_SIZE] for i in range(0, len(combos), BATCH_SIZE)]
  key_batches = [keys[i:i+BATCH_SIZE] for i in range(0, len(keys), BATCH_SIZE)]

  print(f"Classifying {len(combos)} combos in {len(batches)} batches (batch_size={BATCH_SIZE}) ...")
  for i, (batch, kbatch) in enumerate(zip(batches, key_batches)):
    print(f"  batch {i+1}/{len(batches)} ({len(batch)} combos) ...", end=" ")
    t0 = time.time()
    try:
      results = _classify_batch(client, batch)
      for key, result in zip(kbatch, results):
        mapping[key] = result
      print(f"ok ({time.time()-t0:.1f}s)")
    except Exception as e:
      print(f"ERROR: {e}")
      # fill with unknown on failure
      for key in kbatch:
        mapping[key] = {
          "category": "Unknown / Other",
          "subcategory_en": "Classification failed",
          "severity": "low",
          "is_network_fault": False,
        }
    time.sleep(0.3)  # gentle rate limiting

  # write mapping (combo -> classification)
  mapping_out = []
  for combo, cls in zip(combos, [mapping[k] for k in keys]):
    mapping_out.append({**combo, **cls})

  with open(mapping_path, "w", encoding="utf-8") as f:
    json.dump(mapping_out, f, ensure_ascii=False, indent=2)
  print(f"Wrote {mapping_path}  ({len(mapping_out)} entries)")

  # apply mapping back to all tickets
  print("Applying mapping to all tickets ...")
  for t in tickets:
    key = _make_combo_key(t.get("faulttype"), t.get("subcategory"), t.get("faultcause"))
    cls = mapping.get(key, {
      "category": "Unknown / Other",
      "subcategory_en": "",
      "severity": "low",
      "is_network_fault": False,
    })
    t["category"]       = cls.get("category", "Unknown / Other")
    t["subcategory_en"] = cls.get("subcategory_en", "")
    t["severity"]       = cls.get("severity", "low")
    t["is_network_fault"] = cls.get("is_network_fault", False)

  with open(out_path, "w", encoding="utf-8") as f:
    for t in tickets:
      f.write(json.dumps(t, ensure_ascii=False, default=str) + "\n")

  size_mb = out_path.stat().st_size / 1024**2

  # summary
  from collections import Counter
  cat_counts = Counter(t["category"] for t in tickets)
  print(f"Wrote {out_path}  ({size_mb:.1f} MB)")
  print()
  print("Category breakdown:")
  for cat, count in cat_counts.most_common():
    print(f"  {count:>8,}  {cat}")


if __name__ == "__main__":
  classify()
