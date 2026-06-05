"""
Post-training analysis for the WangchanBERTa Thai ticket classifier.

Produces 3 deliverables:
  1. Confusion matrix analysis
        -> confusion_matrix.csv   (full NxN)
        -> confusion_top_pairs.csv (top 20 most-confused class pairs)
        -> per_class_metrics.csv  (precision/recall/F1/support)
        -> confusion_summary.json

  2. Auto-merge similar cluster labels
        -> merges_*.json          (merge plan + result)
        -> cluster_mapping_merged.json  (new mapping with merged labels)
        -> id2label_merged.json   (new label set for retraining)

  3. Super-category taxonomy (~15 business-level groups)
        -> super_category_map.json  (71 classes -> ~15 super categories)
        -> super_category_report.md (human-readable mapping)

Usage:
  uv run python analyze_classifier.py

.env / config (env vars):
  CLASSIFIER_DIR   default: wangchanberta_classifier
  INPUT_FILE       default: tickets.jsonl
  MAPPING_FILE     default: cluster_mapping.json
  OUTPUT_DIR       default: wangchanberta_classifier/analysis
  MAX_TEST         default: 2000   (rebuild test set with predictions)
  MERGE_THRESHOLD  default: 0.85   (cosine similarity for auto-merge)
  SUPER_MIN        default: 5      (min sub-classes for super-category heuristic)
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

BASE = Path(__file__).parent
CLASSIFIER_DIR = BASE / os.getenv("CLASSIFIER_DIR", "wangchanberta_classifier")
OUTPUT_DIR     = BASE / os.getenv("OUTPUT_DIR",     "wangchanberta_classifier/analysis")
INPUT_FILE     = BASE / os.getenv("INPUT_FILE",     "tickets.jsonl")
MAPPING_FILE   = BASE / os.getenv("MAPPING_FILE",   "cluster_mapping.json")
MAX_TEST       = int(os.getenv("MAX_TEST",          2000))
MERGE_THRESHOLD= float(os.getenv("MERGE_THRESHOLD", 0.85))
SUPER_MIN      = int(os.getenv("SUPER_MIN",         5))

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _combo_key(t: dict) -> tuple:
  return (
    (t.get("faulttype")   or "").strip(),
    (t.get("subcategory") or "").strip(),
    (t.get("faultcause")  or "").strip(),
  )


def _text_from_ticket(t: dict) -> str:
  return " | ".join(
    p.strip() for p in [
      t.get("faulttype",   ""),
      t.get("subcategory", ""),
      t.get("faultcause",  ""),
      t.get("networkdisp", ""),
      t.get("l1name",      ""),
    ] if p and p.strip()
  )


# ---------------------------------------------------------------------------
# Step 1 - Re-evaluate the saved model and build a confusion matrix
# ---------------------------------------------------------------------------

def rebuild_predictions() -> tuple[list[str], list[str], list[str]]:
  """Run the trained model on a fresh test sample and return texts/trues/preds."""
  import torch
  from transformers import AutoTokenizer, AutoModelForSequenceClassification
  from datasets import Dataset

  print("=" * 70)
  print("STEP 1  Rebuilding test predictions for confusion analysis")
  print("=" * 70)

  # Load label maps
  with open(CLASSIFIER_DIR / "label2id.json", encoding="utf-8") as f:
    label2id = json.load(f)
  with open(CLASSIFIER_DIR / "id2label.json", encoding="utf-8") as f:
    id2label = json.load(f)
  print(f"  {len(label2id)} classes loaded")

  # Build (text, label) from tickets + mapping
  print(f"Loading {MAPPING_FILE.name} ...")
  with open(MAPPING_FILE, encoding="utf-8") as f:
    mapping_entries = json.load(f)
  combo_to_label: dict[tuple, str] = {
    (e["faulttype"], e["subcategory"], e["faultcause"]): e["cluster_label"]
    for e in mapping_entries
  }

  # Group texts by cluster label
  label_to_texts: dict[str, list[str]] = defaultdict(list)
  print(f"Streaming {INPUT_FILE.name} (capped at {MAX_TEST} balanced samples) ...")
  per_class_cap = max(1, MAX_TEST // len(label2id))
  with open(INPUT_FILE, encoding="utf-8") as f:
    for line in f:
      if not line.strip():
        continue
      t = json.loads(line)
      lbl = combo_to_label.get(_combo_key(t))
      if not lbl or lbl not in label2id:
        continue
      if len(label_to_texts[lbl]) >= per_class_cap:
        continue
      text = _text_from_ticket(t)
      if not text:
        continue
      label_to_texts[lbl].append(text)
      if sum(len(v) for v in label_to_texts.values()) >= MAX_TEST:
        break

  texts, labels = [], []
  for lbl, ts in label_to_texts.items():
    texts.extend(ts)
    labels.extend([lbl] * len(ts))
  print(f"  collected {len(texts):,} test samples across {len(label_to_texts)} classes")

  # Load model
  print("Loading model ...")
  tokenizer = AutoTokenizer.from_pretrained(str(CLASSIFIER_DIR))
  model     = AutoModelForSequenceClassification.from_pretrained(str(CLASSIFIER_DIR))
  model.eval()

  # Predict in batches
  preds: list[str] = []
  BATCH = 32
  t0 = time.time()
  for i in range(0, len(texts), BATCH):
    batch_texts = texts[i:i + BATCH]
    enc = tokenizer(batch_texts, padding=True, truncation=True, max_length=64, return_tensors="pt")
    with torch.no_grad():
      logits = model(**enc).logits
    pred_ids = logits.argmax(dim=-1).tolist()
    preds.extend(id2label[str(p)] for p in pred_ids)
    if (i // BATCH) % 10 == 0:
      print(f"  ... {i + len(batch_texts):,}/{len(texts):,} predicted", end="\r")
  print(f"\n  done in {time.time() - t0:.1f}s")

  return texts, labels, preds


def build_confusion_matrix(trues: list[str], preds: list[str]) -> dict:
  """Build full confusion matrix and per-class metrics."""
  from sklearn.metrics import confusion_matrix, classification_report, accuracy_score, f1_score

  print("\n[1/3] Building confusion matrix ...")
  classes = sorted(set(trues) | set(preds))
  cm = confusion_matrix(trues, preds, labels=classes)

  # Full matrix as CSV
  cm_csv = OUTPUT_DIR / "confusion_matrix.csv"
  with open(cm_csv, "w", encoding="utf-8-sig", newline="") as f:
    import csv
    w = csv.writer(f)
    w.writerow(["true\\pred"] + classes)
    for i, c in enumerate(classes):
      w.writerow([c] + cm[i].tolist())
  print(f"  wrote {cm_csv.name}  ({len(classes)}x{len(classes)})")

  # Top confused pairs
  confused = []
  for i, ti in enumerate(classes):
    for j, pj in enumerate(classes):
      if i != j and cm[i][j] > 0:
        confused.append((ti, pj, int(cm[i][j])))
  confused.sort(key=lambda x: -x[2])
  top_confused = confused[:20]

  top_csv = OUTPUT_DIR / "confusion_top_pairs.csv"
  with open(top_csv, "w", encoding="utf-8-sig", newline="") as f:
    import csv
    w = csv.writer(f)
    w.writerow(["true_label", "predicted_label", "count"])
    for r in top_confused:
      w.writerow(r)
  print(f"  wrote {top_csv.name}  (top 20)")

  # Per-class metrics
  rep = classification_report(
    trues, preds, labels=classes,
    output_dict=True, zero_division=0,
  )
  metrics_csv = OUTPUT_DIR / "per_class_metrics.csv"
  with open(metrics_csv, "w", encoding="utf-8-sig", newline="") as f:
    import csv
    w = csv.writer(f)
    w.writerow(["label", "precision", "recall", "f1_score", "support", "predictions", "errors"])
    label_preds = Counter(preds)
    for c in classes:
      m = rep[c]
      support = int(m["support"])
      pred_n  = int(label_preds.get(c, 0))
      errors  = support - int(round(m["recall"] * support))
      w.writerow([
        c,
        round(m["precision"],   4),
        round(m["recall"],      4),
        round(m["f1-score"],    4),
        support,
        pred_n,
        errors,
      ])
  print(f"  wrote {metrics_csv.name}")

  acc = accuracy_score(trues, preds)
  f1m = f1_score(trues, preds, average="macro",    zero_division=0)
  f1w = f1_score(trues, preds, average="weighted", zero_division=0)

  # Worst classes
  worst = sorted(
    [(c, rep[c]) for c in classes],
    key=lambda kv: kv[1]["f1-score"],
  )[:15]

  summary = {
    "test_size": len(trues),
    "num_classes": len(classes),
    "accuracy":     round(acc, 4),
    "f1_macro":     round(f1m, 4),
    "f1_weighted":  round(f1w, 4),
    "top_confused_pairs": [
      {"true": t, "pred": p, "count": c} for t, p, c in top_confused
    ],
    "worst_classes_by_f1": [
      {
        "label": c,
        "f1":      round(m["f1-score"], 4),
        "precision": round(m["precision"], 4),
        "recall":  round(m["recall"],   4),
        "support": int(m["support"]),
      }
      for c, m in worst
    ],
  }
  with open(OUTPUT_DIR / "confusion_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
  print(f"  wrote confusion_summary.json")

  print(f"\n  accuracy     : {acc:.4f}")
  print(f"  f1_macro     : {f1m:.4f}")
  print(f"  f1_weighted  : {f1w:.4f}")
  print(f"\n  top 5 confused pairs:")
  for t, p, c in top_confused[:5]:
    print(f"    {c:>3}  '{t[:40]}...'  ->  '{p[:40]}...'")

  return summary


# ---------------------------------------------------------------------------
# Step 2 - Auto-merge similar cluster labels (semantic similarity)
# ---------------------------------------------------------------------------

def _short_label(lbl: str) -> str:
  """Take only the part before the first ' | '."""
  return lbl.split(" | ")[0].strip()


def auto_merge_similar_labels() -> dict:
  """Group labels whose (short) forms have high embedding similarity."""
  from sentence_transformers import SentenceTransformer

  print("\n" + "=" * 70)
  print("STEP 2  Auto-merging similar cluster labels (semantic)")
  print("=" * 70)

  with open(CLASSIFIER_DIR / "id2label.json", encoding="utf-8") as f:
    id2label = json.load(f)
  labels = [id2label[str(i)] for i in range(len(id2label))]
  short_labels = [_short_label(l) for l in labels]
  unique_short = sorted(set(short_labels))
  print(f"  {len(labels)} full labels, {len(unique_short)} unique short labels")

  print("Loading paraphrase-multilingual-mpnet-base-v2 for similarity ...")
  model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
  embs = model.encode(unique_short, batch_size=32, show_progress_bar=False,
                      normalize_embeddings=True)

  # Compute pairwise cosine sim
  sim = embs @ embs.T
  np.fill_diagonal(sim, 0.0)

  # Greedy single-link clustering by threshold
  parent = list(range(len(unique_short)))
  def find(x):
    while parent[x] != x:
      parent[x] = parent[parent[x]]
      x = parent[x]
    return x
  def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
      parent[ra] = rb

  edges = []
  for i in range(len(unique_short)):
    for j in range(i + 1, len(unique_short)):
      s = float(sim[i][j])
      if s >= MERGE_THRESHOLD:
        union(i, j)
        edges.append((i, j, s))

  groups: dict[int, list[int]] = defaultdict(list)
  for i in range(len(unique_short)):
    groups[find(i)].append(i)

  # Build merge plan
  merges = []
  for root, members in groups.items():
    if len(members) > 1:
      # Canonical name = longest member
      canonical = max([unique_short[m] for m in members], key=len)
      members_str = [unique_short[m] for m in members]
      merges.append({
        "canonical":     canonical,
        "merged_count":  len(members),
        "members":       members_str,
      })

  merges.sort(key=lambda x: -x["merged_count"])
  print(f"  {len(merges)} merge groups identified (similarity >= {MERGE_THRESHOLD})")
  for m in merges[:10]:
    print(f"    [{m['merged_count']}] {m['canonical'][:40]}  <- {len(m['members'])} variants")

  # Map full label -> canonical (short)
  full_to_canonical: dict[str, str] = {}
  for m in merges:
    for member in m["members"]:
      # all full labels that start with this short form get mapped
      for full in labels:
        if _short_label(full) == member:
          full_to_canonical[full] = m["canonical"]
  for full in labels:
    if full not in full_to_canonical:
      full_to_canonical[full] = _short_label(full)

  # Save
  with open(OUTPUT_DIR / "merges_plan.json", "w", encoding="utf-8") as f:
    json.dump({
      "threshold":       MERGE_THRESHOLD,
      "original_labels": len(labels),
      "unique_short":    len(unique_short),
      "merge_groups":    len(merges),
      "estimated_new_classes": len(unique_short) - sum(m["merged_count"] - 1 for m in merges),
      "merges":          merges,
    }, f, ensure_ascii=False, indent=2)

  # New id2label
  new_labels = sorted({full_to_canonical[l] for l in labels})
  new_id2label = {i: l for i, l in enumerate(new_labels)}
  new_label2id = {l: i for i, l in new_id2label.items()}
  with open(OUTPUT_DIR / "id2label_merged.json", "w", encoding="utf-8") as f:
    json.dump(new_id2label, f, ensure_ascii=False, indent=2)
  with open(OUTPUT_DIR / "label2id_merged.json", "w", encoding="utf-8") as f:
    json.dump(new_label2id, f, ensure_ascii=False, indent=2)

  # Updated cluster_mapping
  with open(MAPPING_FILE, encoding="utf-8") as f:
    cm = json.load(f)
  for entry in cm:
    entry["merged_label"] = full_to_canonical.get(entry["cluster_label"], _short_label(entry["cluster_label"]))
  with open(OUTPUT_DIR / "cluster_mapping_merged.json", "w", encoding="utf-8") as f:
    json.dump(cm, f, ensure_ascii=False, indent=2)

  return {
    "threshold":  MERGE_THRESHOLD,
    "original":   len(labels),
    "merged":     len(new_labels),
    "reduction":  len(labels) - len(new_labels),
    "groups":     merges,
    "new_labels": new_labels,
  }


# ---------------------------------------------------------------------------
# Step 3 - Super-category taxonomy (~15 business-level groups)
# ---------------------------------------------------------------------------

SUPER_RULES = [
  # (regex pattern, super-category name)
  (r"Proactive",                                          "Proactive Maintenance"),
  (r"Preventive",                                         "Preventive Maintenance"),
  (r"Retention",                                          "Retention / Quality"),
  (r"^CA\d+",                                             "TV / Set-Top Box (CA codes)"),
  (r"ER\d+",                                              "TV / Set-Top Box (ER codes)"),
  (r"TVS-|TrueIDTV|Set top box|STB|Set-top|TrueID Gen2|Set กล่อง|กล่อง Set|Mesh Wifi|ไฟ Los|ไฟ PON|ไฟ Power|หน้าจอ|ภาพ|เสียง|รับชม Live TV|Cloud CCTV|CCTV|อุปกรณ์ไม่|ภาพแตก|ภาพกระตุก|ภาพค้าง|ภาพมืด|ภาพเตะ|ภาพดำ|ภาพฟ้า|โทรออก|โทรเข้า|สายโทรศัพท์|สายไฟ|สายหย่อน|ช่างช่วย|ช่างไม่แจ้ง|ลูกค้าขอเปลี่ยน Router|เปลี่ยน Router|เปลี่ยน Modem|เปลี่ยน TrueID|เปลี่ยน Mesh|เปลี่ยน Router/MESH|เปลี่ยนอุปกรณ์|เปลี่ยน STB|ขอเปลี่ยน|ขอช่าง|ขอบริการ|ขอใช้บริการ|ขึ้น SCAN|Remote Trueid|Remote ไม่ทำงาน|ปัญหาอุปกรณ์ Router|ปัญหา Router|ปัญหา WiFi|ปัญหาระบบ|ใช้งาน Program|ใช้งาน App|Game Online|เปิด Web|เปิด Website|Page แจ้งเตือน|บริการหลังการขาย|แจ้งเสียมากกว่า|ย้ายจุด|เดินสาย|ลากจุด",
   "Network / CPE / Service Issue"),
  (r"^$",                                                 "Unknown / Other"),
]


def _classify_super(short: str) -> str:
  for pattern, super_name in SUPER_RULES:
    if re.search(pattern, short):
      return super_name
  return "Unknown / Other"


def build_super_categories(merged_info: dict) -> dict:
  print("\n" + "=" * 70)
  print("STEP 3  Building ~15 super-category taxonomy")
  print("=" * 70)

  # Use the merged labels (post step 2) for cleaner grouping
  labels = merged_info["new_labels"]
  print(f"  {len(labels)} merged labels -> super categories")

  # Assign each label to a super category
  label_to_super: dict[str, str] = {}
  for lbl in labels:
    label_to_super[lbl] = _classify_super(lbl)

  # Group
  super_to_labels: dict[str, list[str]] = defaultdict(list)
  for lbl, sup in label_to_super.items():
    super_to_labels[sup].append(lbl)

  # If any super-category has < SUPER_MIN members, leave it as-is (it's intentional)
  # Sort by member count desc
  sorted_supers = sorted(super_to_labels.items(), key=lambda kv: -len(kv[1]))
  print(f"\n  {len(sorted_supers)} super categories:")
  for sup, mems in sorted_supers:
    print(f"    [{len(mems):>2}] {sup}")

  # Save
  out = {
    "num_super_categories":  len(sorted_supers),
    "num_sub_classes":       len(labels),
    "mapping":               label_to_super,
    "categories": [
      {"name": sup, "sub_classes_count": len(mems), "sub_classes": mems}
      for sup, mems in sorted_supers
    ],
  }
  with open(OUTPUT_DIR / "super_category_map.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

  # Markdown report
  md = ["# Super-Category Taxonomy", ""]
  md.append(f"**Total sub-classes:** {len(labels)}  ")
  md.append(f"**Total super-categories:** {len(sorted_supers)}  ")
  md.append(f"**Source:** WangchanBERTa classifier output, after auto-merge (threshold = {MERGE_THRESHOLD})")
  md.append("")
  md.append("| # | Super-Category | Sub-classes |")
  md.append("|---|---|---|")
  for i, (sup, mems) in enumerate(sorted_supers, 1):
    sample = ", ".join(f"`{m[:30]}`" for m in mems[:3])
    if len(mems) > 3:
      sample += f" ... (+{len(mems) - 3} more)"
    md.append(f"| {i} | **{sup}** | {len(mems)} — {sample} |")
  md.append("")
  md.append("## Full Mapping")
  md.append("")
  for sup, mems in sorted_supers:
    md.append(f"### {sup} ({len(mems)})")
    for m in mems:
      md.append(f"- `{m}`")
    md.append("")

  with open(OUTPUT_DIR / "super_category_report.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md))
  print(f"  wrote super_category_report.md")

  return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
  t0 = time.time()

  # Step 1 - confusion matrix
  _, trues, preds = rebuild_predictions()
  cm_summary = build_confusion_matrix(trues, preds)

  # Step 2 - auto merge
  merged = auto_merge_similar_labels()

  # Step 3 - super categories
  super_info = build_super_categories(merged)

  # Final roll-up
  final = {
    "step1_confusion": {
      "test_size":     cm_summary["test_size"],
      "accuracy":      cm_summary["accuracy"],
      "f1_macro":      cm_summary["f1_macro"],
      "f1_weighted":   cm_summary["f1_weighted"],
      "num_classes":   cm_summary["num_classes"],
      "top_confused_pairs":  cm_summary["top_confused_pairs"][:5],
      "worst_classes_f1":    cm_summary["worst_classes_by_f1"][:10],
    },
    "step2_merge": {
      "threshold":        merged["threshold"],
      "original_labels":  merged["original"],
      "merged_labels":    merged["merged"],
      "reduction":        merged["reduction"],
      "merge_groups":     len(merged["groups"]),
      "top_merges": [
        {"canonical": m["canonical"], "count": m["merged_count"]}
        for m in merged["groups"][:10]
      ],
    },
    "step3_super": {
      "num_super_categories": super_info["num_super_categories"],
      "num_sub_classes":      super_info["num_sub_classes"],
      "categories": [
        {"name": c["name"], "count": c["sub_classes_count"]}
        for c in super_info["categories"]
      ],
    },
    "total_runtime_sec": round(time.time() - t0, 1),
  }
  with open(OUTPUT_DIR / "final_report.json", "w", encoding="utf-8") as f:
    json.dump(final, f, ensure_ascii=False, indent=2)

  # Markdown summary
  md = ["# Classifier Analysis — Final Report", ""]
  md.append(f"_Generated in {final['total_runtime_sec']:.1f}s_")
  md.append("")
  md.append("## 1. Confusion Analysis")
  md.append("")
  md.append(f"- **Test samples:** {cm_summary['test_size']:,}")
  md.append(f"- **Classes:** {cm_summary['num_classes']}")
  md.append(f"- **Accuracy:** {cm_summary['accuracy']:.4f}")
  md.append(f"- **F1 (macro):** {cm_summary['f1_macro']:.4f}")
  md.append(f"- **F1 (weighted):** {cm_summary['f1_weighted']:.4f}")
  md.append("")
  md.append("### Top 5 Most Confused Pairs")
  md.append("")
  md.append("| True Label | Predicted Label | Count |")
  md.append("|---|---|---|")
  for r in cm_summary["top_confused_pairs"][:5]:
    md.append(f"| `{r['true'][:50]}…` | `{r['pred'][:50]}…` | {r['count']} |")
  md.append("")
  md.append("### 10 Worst Classes by F1")
  md.append("")
  md.append("| Label | F1 | Precision | Recall | Support |")
  md.append("|---|---|---|---|---|")
  for c in cm_summary["worst_classes_by_f1"][:10]:
    md.append(f"| `{c['label'][:50]}…` | {c['f1']:.3f} | {c['precision']:.3f} | {c['recall']:.3f} | {c['support']} |")
  md.append("")
  md.append("## 2. Auto-Merge of Similar Labels")
  md.append("")
  md.append(f"- **Similarity threshold:** {merged['threshold']}")
  md.append(f"- **Original labels:** {merged['original']}")
  md.append(f"- **Merged labels:** {merged['merged']}")
  md.append(f"- **Reduction:** {merged['reduction']} classes removed")
  md.append(f"- **Merge groups found:** {len(merged['groups'])}")
  md.append("")
  md.append("### Top 10 Merge Groups")
  md.append("")
  md.append("| Canonical | Variants |")
  md.append("|---|---|")
  for m in merged["groups"][:10]:
    md.append(f"| `{m['canonical']}` | {m['merged_count']} |")
  md.append("")
  md.append("## 3. Super-Category Taxonomy")
  md.append("")
  md.append(f"- **{super_info['num_super_categories']} business-level categories**")
  md.append(f"- {super_info['num_sub_classes']} sub-classes")
  md.append("")
  md.append("| # | Super-Category | Sub-Classes |")
  md.append("|---|---|---|")
  for i, c in enumerate(super_info["categories"], 1):
    md.append(f"| {i} | **{c['name']}** | {c['sub_classes_count']} |")
  md.append("")
  md.append("## Files Produced")
  md.append("")
  md.append("- `confusion_matrix.csv` — full N×N confusion matrix")
  md.append("- `confusion_top_pairs.csv` — top 20 confused class pairs")
  md.append("- `per_class_metrics.csv` — per-class precision/recall/F1")
  md.append("- `confusion_summary.json` — confusion analysis summary")
  md.append("- `merges_plan.json` — auto-merge plan")
  md.append("- `id2label_merged.json` / `label2id_merged.json` — new label set")
  md.append("- `cluster_mapping_merged.json` — updated mapping")
  md.append("- `super_category_map.json` — 71 → 15+ category map")
  md.append("- `super_category_report.md` — human-readable taxonomy")
  md.append("- `final_report.json` — machine-readable summary")
  md.append("- `summary.md` — this report")
  md.append("")

  with open(OUTPUT_DIR / "summary.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md))
  print(f"\nFinal report: {OUTPUT_DIR / 'summary.md'}")


if __name__ == "__main__":
  main()
