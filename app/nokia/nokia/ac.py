"""Shared AC (Altiplano Controller) RESTCONF helpers.

Discovery is AC-first: a single `list_intents` call enumerates every IBN intent
(devices, fibers, uplinks, ...) which the per-domain modules then partition by
intent-type. Per-intent detail is fetched with `get_intent` (the bare intent GET
returns both `intent-specific-data` config/state and top-level `required-network-state`).
"""

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Optional
from .client import AltiplanoClient, save

log = logging.getLogger(__name__)


def _ibn_base(rel: str) -> str:
  return f"/{rel}-ac/rest/restconf/data/ibn:ibn"


def list_intents(client: AltiplanoClient, output_dir: Optional[Path] = None) -> list[dict]:
  """Enumerate all IBN intents as [{"target", "intent-type"}, ...].

  Note: querying the keyed `intent` list directly 500s ("Missing key value");
  the parent container with a `fields` selector is the working form.
  """
  path = f"{_ibn_base(client.rel)}?fields=intent(target;intent-type)"
  raw = client.get(path)
  intents = raw.get("ibn:ibn", {}).get("intent", [])
  if output_dir is not None:
    by_type = dict(Counter(i.get("intent-type") for i in intents))
    save(output_dir, "01_intents", raw,
         {"intents": intents, "count": len(intents), "by_type": by_type})
  return intents


def load_intents(output_dir: Path) -> list[dict]:
  """Re-read intents from disk (01_intents_normalized.json) — no network."""
  data = json.loads((output_dir / "01_intents_normalized.json").read_text())
  return data["intents"]


def targets_of_type(intents: list[dict], *intent_types: str) -> list[str]:
  """Targets whose intent-type is one of intent_types, preserving order."""
  wanted = set(intent_types)
  return [i["target"] for i in intents if i.get("intent-type") in wanted]


def get_intent(client: AltiplanoClient, target: str, intent_type: str) -> dict:
  """Bare intent GET — returns the full intent (config, state, required-network-state)."""
  path = f"{_ibn_base(client.rel)}/intent={target},{intent_type}"
  raw = client.get(path)
  intent = raw.get("ibn:intent", raw)
  return intent[0] if isinstance(intent, list) else intent
