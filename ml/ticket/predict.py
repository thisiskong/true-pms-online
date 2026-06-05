"""
Predict cluster_id for a new ticket using local embedding similarity.

Workflow:
  1. Exact lookup in cluster_mapping.json (fast, O(1))
  2. If combo is unseen — embed it and find the nearest known combo (fallback)

Usage as CLI:
  uv run python predict.py --faulttype "..." --subcategory "..." --faultcause "..."

Usage as module:
  from predict import Predictor
  p = Predictor()
  result = p.predict("สัญญาณอ่อน", "Internet ขาดหายไป", "สายขาด")
  print(result)  # {"cluster_id": 63, "cluster_label": "...", "match": "exact"}

.env keys:
  HF_TOKEN   -- HuggingFace token (for model download)
  EMBED_MODEL -- default: paraphrase-multilingual-mpnet-base-v2
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

_hf_token = os.getenv("HF_TOKEN")
if _hf_token:
  os.environ["HUGGING_FACE_HUB_TOKEN"] = _hf_token

BASE = Path(__file__).parent


def _combo_key(faulttype: str, subcategory: str, faultcause: str) -> str:
  return "|||".join([
    (faulttype   or "").strip(),
    (subcategory or "").strip(),
    (faultcause  or "").strip(),
  ])


def _combo_text(faulttype: str, subcategory: str, faultcause: str) -> str:
  parts = [p for p in [faulttype, subcategory, faultcause] if p.strip()]
  return " | ".join(parts) if parts else "unknown"


class Predictor:
  def __init__(
    self,
    mapping_file: str = "cluster_mapping.json",
    embed_model: str | None = None,
  ):
    mapping_path = BASE / mapping_file
    if not mapping_path.exists():
      raise FileNotFoundError(f"{mapping_path} not found — run embed_cluster.py first")

    with open(mapping_path, encoding="utf-8") as f:
      entries = json.load(f)

    self._lookup: dict[str, dict] = {}
    for e in entries:
      key = _combo_key(e["faulttype"], e["subcategory"], e["faultcause"])
      self._lookup[key] = {
        "cluster_id":    e["cluster_id"],
        "cluster_label": e["cluster_label"],
      }

    self._entries = entries
    self._embed_model_name = embed_model or os.getenv("EMBED_MODEL", "paraphrase-multilingual-mpnet-base-v2")
    self._model = None
    self._known_embeddings: np.ndarray | None = None
    self._known_keys: list[str] = []

  def _load_embeddings(self) -> None:
    if self._model is not None:
      return
    print(f"Loading embedding model '{self._embed_model_name}' for fallback ...")
    from sentence_transformers import SentenceTransformer
    self._model = SentenceTransformer(self._embed_model_name, token=_hf_token)
    texts = [
      _combo_text(e["faulttype"], e["subcategory"], e["faultcause"])
      for e in self._entries
    ]
    self._known_keys = [
      _combo_key(e["faulttype"], e["subcategory"], e["faultcause"])
      for e in self._entries
    ]
    self._known_embeddings = self._model.encode(texts, show_progress_bar=True, batch_size=64)

  def predict(self, faulttype: str, subcategory: str, faultcause: str) -> dict:
    key = _combo_key(faulttype, subcategory, faultcause)

    # exact match
    if key in self._lookup:
      return {**self._lookup[key], "match": "exact"}

    # fallback: nearest neighbour by embedding
    self._load_embeddings()
    text = _combo_text(faulttype, subcategory, faultcause)
    vec = self._model.encode([text])
    dists = np.linalg.norm(self._known_embeddings - vec, axis=1)
    nearest_idx = int(np.argmin(dists))
    nearest_key = self._known_keys[nearest_idx]
    result = self._lookup[nearest_key]
    return {
      **result,
      "match":    "nearest",
      "distance": float(dists[nearest_idx]),
    }

  def predict_ticket(self, ticket: dict) -> dict:
    return self.predict(
      ticket.get("faulttype")   or "",
      ticket.get("subcategory") or "",
      ticket.get("faultcause")  or "",
    )


if __name__ == "__main__":
  import argparse

  parser = argparse.ArgumentParser(description="Predict cluster for a ticket")
  parser.add_argument("--faulttype",   default="")
  parser.add_argument("--subcategory", default="")
  parser.add_argument("--faultcause",  default="")
  args = parser.parse_args()

  p = Predictor()
  result = p.predict(args.faulttype, args.subcategory, args.faultcause)
  print(json.dumps(result, ensure_ascii=False, indent=2))
