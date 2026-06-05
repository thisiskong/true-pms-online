"""
Export cluster-to-faultcode mapping as CSV for review in Excel.

Reads:  cluster_mapping.json  (combo -> cluster)
    tickets.jsonl          (for ticket counts per combo)
Writes: cluster_faultcode_map.csv

Columns:
  cluster_id | cluster_label | faulttype | subcategory | faultcause | ticket_count
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

base = Path(__file__).parent


def run() -> None:
  mapping_path = base / "cluster_mapping.json"
  tickets_path = base / "tickets.jsonl"
  out_path     = base / "cluster_faultcode_map.csv"

  print(f"Reading {mapping_path} ...")
  with open(mapping_path, encoding="utf-8") as f:
    mapping = json.load(f)

  # count tickets per (faulttype, subcategory, faultcause) combo
  print(f"Counting tickets per combo from {tickets_path} ...")
  combo_counts: Counter = Counter()
  with open(tickets_path, encoding="utf-8") as f:
    for line in f:
      if not line.strip():
        continue
      t = json.loads(line)
      key = (
        (t.get("faulttype")   or "").strip(),
        (t.get("subcategory") or "").strip(),
        (t.get("faultcause")  or "").strip(),
      )
      combo_counts[key] += 1

  # build rows
  rows = []
  for entry in mapping:
    key = (
      entry.get("faulttype",   ""),
      entry.get("subcategory", ""),
      entry.get("faultcause",  ""),
    )
    rows.append({
      "cluster_id":    entry.get("cluster_id", ""),
      "cluster_label": entry.get("cluster_label", ""),
      "faulttype":     entry.get("faulttype",   ""),
      "subcategory":   entry.get("subcategory", ""),
      "faultcause":    entry.get("faultcause",  ""),
      "ticket_count":  combo_counts.get(key, 0),
    })

  # sort by cluster_id then ticket_count desc
  rows.sort(key=lambda r: (r["cluster_id"], -r["ticket_count"]))

  print(f"Writing {out_path} ...")
  with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=[
      "cluster_id", "cluster_label",
      "faulttype", "subcategory", "faultcause", "ticket_count",
    ])
    writer.writeheader()
    writer.writerows(rows)

  total_tickets = sum(r["ticket_count"] for r in rows)
  print(f"Done.")
  print(f"  {len(rows):,} rows written")
  print(f"  {len(set(r['cluster_id'] for r in rows))} clusters")
  print(f"  {total_tickets:,} total tickets covered")
  print(f"  -> Open {out_path.name} in Excel to review and rename cluster_label values")


if __name__ == "__main__":
  run()
