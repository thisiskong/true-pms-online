"""Item 5: ES-ONT — count ONTs per fiber."""

from pathlib import Path
from .client import AltiplanoClient, save


ES_PATH = "/altiplano-indexsearch/intents/_search/"


def fetch(client: AltiplanoClient, fiber_name: str) -> dict:
  body = {
    "from": "0",
    "size": "0",  # count only — no need to return docs
    "query": {
      "bool": {
        "filter": [{"term": {"intent-type": "ont"}}],
        "must": [{"match": {"configuration.fiber-name": fiber_name}}],
      }
    },
  }
  return client.post(ES_PATH, body=body, es=True)


def normalize(raw: dict, fiber_name: str) -> dict:
  return {
    "fiber_name": fiber_name,
    "ont_count": raw.get("hits", {}).get("total", {}).get("value", 0),
  }


def run(client: AltiplanoClient, output_dir: Path, fibers_by_olt: dict[str, list[dict]]) -> dict[str, int]:
  all_raw: dict[str, dict] = {}
  ont_counts: dict[str, int] = {}

  for olt, fibers in fibers_by_olt.items():
    print(f"[ES-ONT] OLT={olt} ({len(fibers)} fibers) ...")
    for fiber in fibers:
      fname = fiber["fiber_name"]
      raw = fetch(client, fname)
      count = raw.get("hits", {}).get("total", {}).get("value", 0)
      all_raw[fname] = raw
      ont_counts[fname] = count
    print(f"  total ONTs: {sum(ont_counts[f['fiber_name']] for f in fibers)}")

  normalized = [
    {"fiber_name": k, "ont_count": v}
    for k, v in ont_counts.items()
  ]
  save(output_dir, "05_es_ont", all_raw, {"ont_counts": normalized, "grand_total": sum(ont_counts.values())})
  return ont_counts
