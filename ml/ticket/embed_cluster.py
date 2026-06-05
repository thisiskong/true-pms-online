"""
Embedding + clustering approach for ticket classification (fully local, no API).

Workflow:
  1. Read tickets.jsonl
  2. Extract distinct (faulttype, subcategory, faultcause) combos
  3. Embed combos using multilingual sentence-transformers (local, supports Thai)
  4. Cluster with HDBSCAN (auto-discovers number of clusters)
  5. Auto-label each cluster from the most frequent faulttype in that cluster
  6. Apply cluster labels to all tickets
  7. Write cluster_mapping.json + tickets_clustered.jsonl

Usage:
  uv run python embed_cluster.py

.env keys:
  HF_TOKEN                 -- Hugging Face token (for model download)
  INPUT_FILE               -- default: tickets.jsonl
  CLUSTERED_FILE           -- default: tickets_clustered.jsonl
  EMBED_MODEL              -- default: paraphrase-multilingual-mpnet-base-v2
  HDBSCAN_MIN_CLUSTER_SIZE -- default: 5
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

# set HF token for model download if provided
_hf_token = os.getenv("HF_TOKEN")
if _hf_token:
  os.environ["HUGGING_FACE_HUB_TOKEN"] = _hf_token


def _combo_text(faulttype: str, subcategory: str, faultcause: str) -> str:
  parts = [p for p in [faulttype, subcategory, faultcause] if p.strip()]
  return " | ".join(parts) if parts else "unknown"


def _combo_key(faulttype, subcategory, faultcause) -> str:
  return "|||".join([
    (faulttype   or "").strip(),
    (subcategory or "").strip(),
    (faultcause  or "").strip(),
  ])


def _auto_label_clusters(cluster_samples: dict[int, list[str]]) -> dict[int, str]:
  """Label each cluster by its most frequent text."""
  labels = {}
  for cid, texts in cluster_samples.items():
    most_common = Counter(texts).most_common(1)[0][0]
    # trim to reasonable length for a label
    label = most_common[:60] if len(most_common) > 60 else most_common
    labels[cid] = label
  return labels


def run(
  input_file: str = "tickets.jsonl",
  clustered_file: str = "tickets_clustered.jsonl",
) -> None:
  base = Path(__file__).parent
  in_path  = base / os.getenv("INPUT_FILE",     input_file)
  out_path = base / os.getenv("CLUSTERED_FILE", clustered_file)
  embed_model = os.getenv("EMBED_MODEL", "paraphrase-multilingual-mpnet-base-v2")
  min_cluster = int(os.getenv("HDBSCAN_MIN_CLUSTER_SIZE", 20))

  if not in_path.exists():
    print(f"ERROR: {in_path} not found. Run load_tickets.py first.")
    return

  print(f"Reading {in_path} ...")
  with open(in_path, encoding="utf-8") as f:
    tickets = [json.loads(line) for line in f if line.strip()]
  print(f"  {len(tickets):,} tickets")

  # distinct combos
  seen: dict[str, tuple] = {}
  for t in tickets:
    k = _combo_key(t.get("faulttype"), t.get("subcategory"), t.get("faultcause"))
    if k not in seen:
      seen[k] = (
        (t.get("faulttype")   or "").strip(),
        (t.get("subcategory") or "").strip(),
        (t.get("faultcause")  or "").strip(),
      )

  keys   = list(seen.keys())
  combos = list(seen.values())
  texts  = [_combo_text(*c) for c in combos]
  print(f"  {len(texts)} distinct combos to embed")

  # --- Step 1: Embed -------------------------------------------------------
  print(f"Loading embedding model '{embed_model}' (downloads once to HF cache) ...")
  from sentence_transformers import SentenceTransformer
  model = SentenceTransformer(embed_model, token=_hf_token)
  print("Embedding ...")
  embeddings = model.encode(texts, show_progress_bar=True, batch_size=64)
  print(f"  embeddings shape: {embeddings.shape}")

  # --- Step 2: Cluster -----------------------------------------------------
  print(f"Clustering (HDBSCAN min_cluster_size={min_cluster}) ...")
  import hdbscan
  clusterer = hdbscan.HDBSCAN(
    min_cluster_size=min_cluster,
    min_samples=1,
    metric="euclidean",
  )
  labels = clusterer.fit_predict(embeddings)
  n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
  n_noise    = int((labels == -1).sum())
  print(f"  {n_clusters} clusters found, {n_noise} noise points (assigned to nearest cluster)")

  # assign noise points to nearest cluster centroid
  if n_noise > 0 and n_clusters > 0:
    cluster_ids = [l for l in set(labels) if l != -1]
    centroids = np.array([
      embeddings[labels == cid].mean(axis=0) for cid in cluster_ids
    ])
    for i, lbl in enumerate(labels):
      if lbl == -1:
        dists = np.linalg.norm(centroids - embeddings[i], axis=1)
        labels[i] = cluster_ids[int(np.argmin(dists))]

  # --- Step 3: Auto-label clusters from most frequent text -----------------
  cluster_samples: dict[int, list[str]] = {}
  for txt, lbl in zip(texts, labels):
    cluster_samples.setdefault(int(lbl), []).append(txt)

  cluster_labels = _auto_label_clusters(cluster_samples)
  print(f"  {len(cluster_labels)} cluster labels assigned automatically")

  # build key -> cluster info
  key_to_info: dict[str, dict] = {}
  for key, lbl in zip(keys, labels):
    cid = int(lbl)
    key_to_info[key] = {"cluster_id": cid, "cluster_label": cluster_labels.get(cid, f"Cluster-{cid}")}

  # write cluster mapping (for manual review / relabelling)
  mapping_path = base / "cluster_mapping.json"
  mapping_out = []
  for (ft, sc, fc), txt, lbl in zip(combos, texts, labels):
    cid = int(lbl)
    mapping_out.append({
      "faulttype": ft,
      "subcategory": sc,
      "faultcause": fc,
      "cluster_id": cid,
      "cluster_label": cluster_labels.get(cid, f"Cluster-{cid}"),
      "sample_text": txt,
      "cluster_size": len(cluster_samples.get(cid, [])),
    })
  # sort by cluster_id for easy review
  mapping_out.sort(key=lambda x: x["cluster_id"])
  with open(mapping_path, "w", encoding="utf-8") as f:
    json.dump(mapping_out, f, ensure_ascii=False, indent=2)
  print(f"Wrote {mapping_path}  ({len(mapping_out)} entries)")
  print(f"  -> Review and edit cluster_label values in this file to rename clusters")

  # --- Step 4: Apply to all tickets ----------------------------------------
  print("Applying cluster labels to all tickets ...")
  with open(out_path, "w", encoding="utf-8") as f:
    for t in tickets:
      k    = _combo_key(t.get("faulttype"), t.get("subcategory"), t.get("faultcause"))
      info = key_to_info.get(k, {"cluster_id": -1, "cluster_label": "Unknown"})
      t["cluster_id"]    = info["cluster_id"]
      t["cluster_label"] = info["cluster_label"]
      f.write(json.dumps(t, ensure_ascii=False, default=str) + "\n")

  size_mb = out_path.stat().st_size / 1024**2
  print(f"Wrote {out_path}  ({size_mb:.1f} MB)")

  print()
  print("Cluster breakdown (top 20):")
  label_counts = Counter(info["cluster_label"] for info in key_to_info.values())
  for label, count in label_counts.most_common(20):
    print(f"  {count:>6}  {label}")


if __name__ == "__main__":
  run()
