"""
Improved auto-merge: lower threshold + more aggressive duplicate detection.

This merges labels whose short forms are highly similar (cosine >= MERGE_THRESHOLD)
OR have very high Jaccard/containment overlap.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

BASE = Path(__file__).parent
CLASSIFIER_DIR = BASE / "wangchanberta_classifier"
OUTPUT_DIR     = CLASSIFIER_DIR / "analysis"
MERGE_THRESHOLD = float(os.getenv("MERGE_THRESHOLD", 0.70))   # lowered from 0.85


def _short(lbl: str) -> str:
  return lbl.split(" | ")[0].strip()


def _jaccard(a: str, b: str) -> float:
  """Word-level Jaccard similarity (better for short Thai labels)."""
  aw = set(re.findall(r"\w+", a.lower()))
  bw = set(re.findall(r"\w+", b.lower()))
  if not aw or not bw:
    return 0.0
  return len(aw & bw) / len(aw | bw)


def _containment(a: str, b: str) -> float:
  """What fraction of shorter string's words are in longer."""
  aw = set(re.findall(r"\w+", a.lower()))
  bw = set(re.findall(r"\w+", b.lower()))
  if not aw or not bw:
    return 0.0
  small, big = (aw, bw) if len(aw) <= len(bw) else (bw, aw)
  return len(small & big) / len(small)


def main():
  import json as _json
  print("=" * 70)
  print("Improved auto-merge (lower threshold + Jaccard)")
  print("=" * 70)

  with open(CLASSIFIER_DIR / "id2label.json", encoding="utf-8") as f:
    id2label = _json.load(f)
  labels = [_short(id2label[str(i)]) for i in range(len(id2label))]
  unique = sorted(set(labels))
  print(f"  {len(labels)} full labels, {len(unique)} unique short labels")

  # Step A: Embedding-based similarity
  from sentence_transformers import SentenceTransformer
  print("Loading multilingual sentence-transformer ...")
  model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
  embs = model.encode(unique, batch_size=32, show_progress_bar=False,
                      normalize_embeddings=True)
  sim = embs @ embs.T
  np.fill_diagonal(sim, 0.0)

  # Step B: Jaccard similarity matrix
  jacc = np.zeros_like(sim)
  for i in range(len(unique)):
    for j in range(i + 1, len(unique)):
      jv = _jaccard(unique[i], unique[j])
      jacc[i][j] = jacc[j][i] = jv

  # Step C: Combined similarity
  combined = np.maximum(sim, jacc)

  # Step D: Single-link clustering at threshold
  parent = list(range(len(unique)))
  def find(x):
    while parent[x] != x:
      parent[x] = parent[parent[x]]
      x = parent[x]
    return x
  def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
      parent[ra] = rb

  edges_added = 0
  for i in range(len(unique)):
    for j in range(i + 1, len(unique)):
      if combined[i][j] >= MERGE_THRESHOLD:
        union(i, j)
        edges_added += 1
  print(f"  {edges_added} edges added at threshold >= {MERGE_THRESHOLD}")

  groups: dict[int, list[int]] = defaultdict(list)
  for i in range(len(unique)):
    groups[find(i)].append(i)

  merges = []
  for root, members in groups.items():
    if len(members) > 1:
      canonical = max([unique[m] for m in members], key=len)
      merges.append({
        "canonical":     canonical,
        "merged_count":  len(members),
        "members":       [unique[m] for m in members],
        "max_jaccard":   float(max(jacc[m1][m2] for m1 in members for m2 in members if m1 != m2) or 0),
        "max_embed":     float(max(sim[m1][m2]  for m1 in members for m2 in members if m1 != m2) or 0),
      })
  merges.sort(key=lambda x: -x["merged_count"])
  print(f"  {len(merges)} merge groups identified")
  for m in merges[:15]:
    print(f"    [{m['merged_count']}] jacc={m['max_jaccard']:.2f} emb={m['max_embed']:.2f}  {m['canonical'][:50]}")

  # Map full -> short canonical
  full_to_canonical: dict[str, str] = {}
  for m in merges:
    for member in m["members"]:
      for full in labels:
        if _short(full) == member:
          full_to_canonical[full] = m["canonical"]
  for full in labels:
    if full not in full_to_canonical:
      full_to_canonical[full] = _short(full)

  # Save
  with open(OUTPUT_DIR / "merges_plan.json", "w", encoding="utf-8") as f:
    _json.dump({
      "threshold":       MERGE_THRESHOLD,
      "method":          "embed_max_jaccard",
      "original_labels": len(labels),
      "unique_short":    len(unique),
      "merge_groups":    len(merges),
      "estimated_new_classes": len(unique) - sum(m["merged_count"] - 1 for m in merges),
      "merges":          merges,
    }, f, ensure_ascii=False, indent=2)

  new_labels = sorted({full_to_canonical[l] for l in labels})
  new_id2label = {i: l for i, l in enumerate(new_labels)}
  new_label2id = {l: i for i, l in new_id2label.items()}
  with open(OUTPUT_DIR / "id2label_merged.json", "w", encoding="utf-8") as f:
    _json.dump(new_id2label, f, ensure_ascii=False, indent=2)
  with open(OUTPUT_DIR / "label2id_merged.json", "w", encoding="utf-8") as f:
    _json.dump(new_label2id, f, ensure_ascii=False, indent=2)

  with open(OUTPUT_DIR / "cluster_mapping_merged.json", "w", encoding="utf-8") as f:
    with open(BASE / "cluster_mapping.json", encoding="utf-8") as f2:
      cm = _json.load(f2)
    for entry in cm:
      entry["merged_label"] = full_to_canonical.get(entry["cluster_label"], _short(entry["cluster_label"]))
    _json.dump(cm, f, ensure_ascii=False, indent=2)

  # Update final_report
  with open(OUTPUT_DIR / "final_report.json", encoding="utf-8") as f:
    final = _json.load(f)
  final["step2_merge"] = {
    "threshold":         MERGE_THRESHOLD,
    "method":            "embed_max_jaccard",
    "original_labels":   len(labels),
    "merged_labels":     len(new_labels),
    "reduction":         len(labels) - len(new_labels),
    "merge_groups":      len(merges),
    "top_merges": [
      {"canonical": m["canonical"], "count": m["merged_count"],
       "max_jaccard": round(m["max_jaccard"], 3),
       "max_embed":   round(m["max_embed"],   3)}
      for m in merges[:15]
    ],
  }
  with open(OUTPUT_DIR / "final_report.json", "w", encoding="utf-8") as f:
    _json.dump(final, f, ensure_ascii=False, indent=2)

  print(f"\nDone. New label count: {len(new_labels)} (down from {len(labels)})")


if __name__ == "__main__":
  main()
