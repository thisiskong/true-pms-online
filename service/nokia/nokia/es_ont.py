"""Item 5: ES-ONT — list ONTs per fiber (names + count)."""

import logging
from pathlib import Path
from .client import AltiplanoClient, save

log = logging.getLogger(__name__)


ES_PATH = "/altiplano-indexsearch/intents/_search/"


def fetch(client: AltiplanoClient, fiber_name: str) -> dict:
  body = {
    "from": "0",
    "size": "9999",
    "query": {
      "bool": {
        "filter": [{"term": {"intent-type": "ont"}}],
        "must": [{"match": {"configuration.fiber-name": fiber_name}}],
      }
    },
    "_source": ["target", "configuration"],
  }
  return client.post(ES_PATH, body=body, es=True)


def normalize(raw: dict, fiber_name: str) -> list[dict]:
  hits = raw.get("hits", {}).get("hits", [])
  onts = []
  for hit in hits:
    src = hit.get("_source", {})
    target = src.get("target", {})
    ont_name = target.get("ont-name") or hit.get("_id")
    cfg = src.get("configuration", {})
    onts.append({
      "fiber_name": fiber_name,
      "ont_name": ont_name,
      "serial_number": (cfg.get("serial-number") or [None])[0],
    })
  return onts


def run(
  client: AltiplanoClient,
  output_dir: Path,
  fibers_by_olt: dict[str, list[dict]],
) -> tuple[dict[str, int], dict[str, list[str]]]:
  """Returns (ont_counts, ont_names_by_fiber).

  ont_counts: fiber_name -> count
  ont_names_by_fiber: fiber_name -> [ont_name, ...]
  """
  all_raw: dict[str, dict] = {}
  ont_counts: dict[str, int] = {}
  ont_names_by_fiber: dict[str, list[str]] = {}

  for olt, fibers in fibers_by_olt.items():
    log.info("[ES-ONT] OLT=%s (%d fibers) ...", olt, len(fibers))
    for fiber in fibers:
      fname = fiber["fiber_name"]
      raw = fetch(client, fname)
      onts = normalize(raw, fname)
      all_raw[fname] = raw
      ont_counts[fname] = len(onts)
      ont_names_by_fiber[fname] = [o["ont_name"] for o in onts if o["ont_name"]]
    log.info("  total ONTs: %d", sum(ont_counts[f["fiber_name"]] for f in fibers))

  normalized = [
    {"fiber_name": k, "ont_count": v, "ont_names": ont_names_by_fiber.get(k, [])}
    for k, v in ont_counts.items()
  ]
  save(output_dir, "05_es_ont", all_raw, {"ont_counts": normalized, "grand_total": sum(ont_counts.values())})
  return ont_counts, ont_names_by_fiber
