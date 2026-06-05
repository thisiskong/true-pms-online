"""
Retrain WangchanBERTa on the 42-class MERGED label set.

This is v2 of classify_wangchanberta.py - same architecture, but uses the
auto-merged labels (from analysis/id2label_merged.json) for cleaner training
and higher accuracy.

Key differences from v1:
  - Uses id2label_merged.json (42 classes) instead of 71
  - Saves to wangchanberta_classifier_v2/
  - Includes super_category in output JSON (via super_category_map.json)

Usage:
  uv run python classify_wangchanberta_v2.py

.env keys (same as v1):
  HF_TOKEN
  INPUT_FILE              default: tickets.jsonl
  MAPPING_FILE            default: cluster_mapping.json
  OUTPUT_DIR              default: wangchanberta_classifier_v2
  ID2LABEL_MERGED         default: wangchanberta_classifier/analysis/id2label_merged.json
  SUPER_CATEGORY_MAP      default: wangchanberta_classifier/analysis/super_category_map.json
  WANGCHAN_MODEL          default: airesearch/wangchanberta-base-att-spm-uncased
  MAX_TRAIN_SAMPLES       default: 30000
  MAX_TEST_SAMPLES        default: 3000
  MAX_SEQ_LEN             default: 96
  BATCH_SIZE              default: 32
  EPOCHS                  default: 2
  LR                      default: 3e-5
  TEST_SPLIT              default: 0.1
  SEED                    default: 42
"""

from __future__ import annotations

import json
import os
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

BASE = Path(__file__).parent
SEED = int(os.getenv("SEED", 42))
random.seed(SEED)
np.random.seed(SEED)


# ---------------------------------------------------------------------------
# Helpers (same as v1)
# ---------------------------------------------------------------------------

def _combo_key(t: dict) -> tuple:
  return (
    (t.get("faulttype")   or "").strip(),
    (t.get("subcategory") or "").strip(),
    (t.get("faultcause")  or "").strip(),
  )


def _text_from_ticket(t: dict) -> str:
  parts = [
    t.get("faulttype",   ""),
    t.get("subcategory", ""),
    t.get("faultcause",  ""),
    t.get("networkdisp", ""),
    t.get("l1name",      ""),
  ]
  return " | ".join(p.strip() for p in parts if p and p.strip())


def _short(lbl: str) -> str:
  return lbl.split(" | ")[0].strip()


# ---------------------------------------------------------------------------
# Data loading with merged labels
# ---------------------------------------------------------------------------

def load_labeled_data() -> tuple[list[tuple[str, str]], int, int, dict[str, str]]:
  """Join tickets with cluster_mapping.json, then map to MERGED labels.

  Returns (pairs, num_combos, total_scanned, combo_to_merged).
  """
  input_file   = BASE / os.getenv("INPUT_FILE",   "tickets.jsonl")
  mapping_file = BASE / os.getenv("MAPPING_FILE", "cluster_mapping.json")
  merged_path  = BASE / os.getenv("ID2LABEL_MERGED",
                                  "wangchanberta_classifier/analysis/id2label_merged.json")

  if not input_file.exists():
    raise FileNotFoundError(f"{input_file} not found")
  if not mapping_file.exists():
    raise FileNotFoundError(f"{mapping_file} not found")
  if not merged_path.exists():
    raise FileNotFoundError(
      f"{merged_path} not found - run merge_similar_labels.py first"
    )

  with open(mapping_file, encoding="utf-8") as f:
    mapping_entries = json.load(f)

  with open(merged_path, encoding="utf-8") as f:
    id2label = json.load(f)
  # Reverse: any cluster_label -> merged canonical (short)
  valid_merged = set(id2label.values())

  # Build combo -> merged-label map
  combo_to_merged: dict[tuple, str] = {}
  for e in mapping_entries:
    full_label = e["cluster_label"]
    short = _short(full_label)
    # If the short form is in the merged set, use it; otherwise try the full
    if short in valid_merged:
      merged = short
    elif full_label in valid_merged:
      merged = full_label
    else:
      # Fallback: use the short form (will keep all 71 distinct, but
      # downstream code can still map)
      merged = short
    combo_to_merged[(_short(full_label),)] = merged  # we'll re-key below
  # Re-key properly using faulttype+subcategory+faultcause
  combo_to_merged = {}
  for e in mapping_entries:
    key = (e["faulttype"], e["subcategory"], e["faultcause"])
    full = e["cluster_label"]
    short = _short(full)
    combo_to_merged[key] = short if short in valid_merged else full

  print(f"  {len(combo_to_merged):,} distinct combos loaded")
  print(f"  merged label set: {len(valid_merged)} classes")

  print(f"Streaming {input_file.name} ...")
  pairs: list[tuple[str, str]] = []
  total_scanned = 0
  with open(input_file, encoding="utf-8") as f:
    for i, line in enumerate(f):
      if not line.strip():
        continue
      total_scanned += 1
      t = json.loads(line)
      key = _combo_key(t)
      label = combo_to_merged.get(key)
      if not label or label not in valid_merged:
        continue
      text = _text_from_ticket(t)
      if not text:
        continue
      pairs.append((text, label))
      if (i + 1) % 100_000 == 0:
        print(f"  ... {i+1:,} tickets scanned, {len(pairs):,} labeled")

  print(f"  {len(pairs):,} labeled tickets collected")
  return pairs, len(combo_to_merged), total_scanned, combo_to_merged


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def balance_sample(pairs: list[tuple[str, str]],
                   max_total: int,
                   min_per_class: int = 5) -> list[tuple[str, str]]:
  by_label: dict[str, list[str]] = {}
  for text, label in pairs:
    by_label.setdefault(label, []).append(text)

  labels_sorted = sorted(by_label.items(), key=lambda kv: -len(kv[1]))
  print(f"  total classes: {len(by_label)}")
  print(f"  class size range: {min(len(v) for v in by_label.values())} "
        f"to {max(len(v) for v in by_label.values())}")

  per_class = max(1, max_total // len(by_label))
  per_class = max(per_class, min_per_class)
  sampled: list[tuple[str, str]] = []
  for label, texts in labels_sorted:
    random.shuffle(texts)
    chosen = texts[:per_class]
    sampled.extend((t, label) for t in chosen)

  random.shuffle(sampled)
  if len(sampled) > max_total:
    sampled = sampled[:max_total]
  print(f"  sampled: {len(sampled):,} (up to {per_class}/class)")
  return sampled


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def run():
  output_dir   = BASE / os.getenv("OUTPUT_DIR", "wangchanberta_classifier_v2")
  model_name   = os.getenv("WANGCHAN_MODEL", "airesearch/wangchanberta-base-att-spm-uncased")
  max_train    = int(os.getenv("MAX_TRAIN_SAMPLES", 30000))
  max_test     = int(os.getenv("MAX_TEST_SAMPLES",  3000))
  max_seq_len  = int(os.getenv("MAX_SEQ_LEN",       96))
  batch_size   = int(os.getenv("BATCH_SIZE",        32))
  epochs       = int(os.getenv("EPOCHS",            2))
  lr           = float(os.getenv("LR",              3e-5))
  test_split   = float(os.getenv("TEST_SPLIT",      0.1))
  hf_token     = os.getenv("HF_TOKEN") or None
  super_map_path = BASE / os.getenv("SUPER_CATEGORY_MAP",
                                    "wangchanberta_classifier/analysis/super_category_map.json")

  output_dir.mkdir(exist_ok=True)
  print("=" * 70)
  print("WangchanBERTa v2 (MERGED 42-class) Ticket Classifier")
  print("=" * 70)
  print(f"  model         : {model_name}")
  print(f"  output dir    : {output_dir.name}/")
  print(f"  max_seq_len   : {max_seq_len}")
  print(f"  batch_size    : {batch_size}")
  print(f"  epochs        : {epochs}")
  print(f"  lr            : {lr}")
  print(f"  max_train     : {max_train:,}")
  print(f"  max_test      : {max_test:,}")
  print()

  # ----- data -----
  print("[1/5] Loading & labeling tickets (with merge map) ...")
  pairs, num_combos, total_scanned, combo_to_merged = load_labeled_data()

  print("\n[2/5] Sampling ...")
  sampled = balance_sample(pairs, max_total=max_train + max_test)
  del pairs

  n_test = min(max_test, max(1, int(len(sampled) * test_split)))
  n_test = min(n_test, len(sampled) // 2)
  test_pairs  = sampled[:n_test]
  train_pairs = sampled[n_test:]
  print(f"  train: {len(train_pairs):,}  test: {len(test_pairs):,}")

  label_list = sorted({lbl for _, lbl in train_pairs + test_pairs})
  label2id = {lbl: i for i, lbl in enumerate(label_list)}
  id2label = {i: lbl for lbl, i in label2id.items()}
  print(f"  classes: {len(label_list)}")

  # ----- model & tokenizer -----
  print("\n[3/5] Loading WangchanBERTa tokenizer & model ...")
  t0 = time.time()
  from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    TrainingArguments,
    Trainer,
    DataCollatorWithPadding,
  )
  import torch
  from datasets import Dataset

  tokenizer = AutoTokenizer.from_pretrained(model_name, token=hf_token)
  model = AutoModelForSequenceClassification.from_pretrained(
    model_name,
    num_labels=len(label_list),
    id2label=id2label,
    label2id=label2id,
    token=hf_token,
  )
  print(f"  loaded in {time.time()-t0:.1f}s")
  print(f"  device: {'cuda' if torch.cuda.is_available() else 'cpu'}")

  # ----- tokenize & build datasets -----
  print("\n[4/5] Tokenizing & building datasets ...")
  def _to_records(pairs: list[tuple[str, str]]) -> list[dict]:
    return [{"text": t, "label": label2id[l]} for t, l in pairs]

  train_records = _to_records(train_pairs)
  test_records  = _to_records(test_pairs)

  def _tokenize(batch):
    return tokenizer(batch["text"], truncation=True, max_length=max_seq_len)

  train_ds = Dataset.from_list(train_records).map(_tokenize, batched=True, remove_columns=["text"])
  test_ds  = Dataset.from_list(test_records).map(_tokenize,  batched=True, remove_columns=["text"])

  collator = DataCollatorWithPadding(tokenizer=tokenizer)

  # ----- training -----
  print("\n[5/5] Training ...")
  args = TrainingArguments(
    output_dir=str(output_dir / "checkpoints"),
    num_train_epochs=epochs,
    per_device_train_batch_size=batch_size,
    per_device_eval_batch_size=batch_size,
    learning_rate=lr,
    weight_decay=0.01,
    eval_strategy="epoch",
    save_strategy="no",
    logging_steps=50,
    report_to="none",
    seed=SEED,
    fp16=torch.cuda.is_available(),
  )

  def _compute_metrics(eval_pred):
    from sklearn.metrics import accuracy_score, f1_score
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {
      "accuracy": accuracy_score(labels, preds),
      "f1_macro": f1_score(labels, preds, average="macro", zero_division=0),
      "f1_weighted": f1_score(labels, preds, average="weighted", zero_division=0),
    }

  trainer = Trainer(
    model=model,
    args=args,
    train_dataset=train_ds,
    eval_dataset=test_ds,
    processing_class=tokenizer,
    data_collator=collator,
    compute_metrics=_compute_metrics,
  )

  t0 = time.time()
  trainer.train()
  train_secs = time.time() - t0
  print(f"  training took {train_secs/60:.1f} min")

  # ----- evaluation -----
  print("\nEvaluating on test set ...")
  metrics = trainer.evaluate()
  print(f"  test accuracy : {metrics['eval_accuracy']:.4f}")
  print(f"  test f1_macro : {metrics['eval_f1_macro']:.4f}")
  print(f"  test f1_weight: {metrics['eval_f1_weighted']:.4f}")

  pred_output = trainer.predict(test_ds)
  preds = np.argmax(pred_output.predictions, axis=-1)
  true  = pred_output.label_ids

  from sklearn.metrics import classification_report
  short_names = {lbl: (lbl[:35] + "…") if len(lbl) > 38 else lbl for lbl in label_list}
  target_names = [short_names[lbl] for lbl in label_list]
  report = classification_report(
    true, preds,
    labels=list(range(len(label_list))),
    target_names=target_names,
    zero_division=0,
  )
  print()
  print(report)

  # ----- save -----
  print(f"\nSaving model to {output_dir}/ ...")
  trainer.save_model(str(output_dir))
  tokenizer.save_pretrained(str(output_dir))

  with open(output_dir / "label2id.json", "w", encoding="utf-8") as f:
    json.dump(label2id, f, ensure_ascii=False, indent=2)
  with open(output_dir / "id2label.json", "w", encoding="utf-8") as f:
    json.dump(id2label, f, ensure_ascii=False, indent=2)

  # ----- super-category map (copied for inference) -----
  if super_map_path.exists():
    import shutil
    shutil.copy(super_map_path, output_dir / "super_category_map.json")
    with open(super_map_path, encoding="utf-8") as f:
      super_map = json.load(f)
    short_to_super = super_map.get("short_to_super", {})
  else:
    short_to_super = {}

  # ----- summary -----
  label_counter = Counter(lbl for _, lbl in train_pairs + test_pairs)
  top_classes = label_counter.most_common(10)
  pred_counter = Counter(int(p) for p in preds)
  correct = int((preds == true).sum())

  summary = {
    "model": model_name,
    "version": "v2-merged-42-classes",
    "device": "cuda" if torch.cuda.is_available() else "cpu",
    "input_file":   os.getenv("INPUT_FILE",   "tickets.jsonl"),
    "mapping_file": os.getenv("MAPPING_FILE", "cluster_mapping.json"),
    "training": {
      "total_tickets_scanned":   total_scanned,
      "total_combos_loaded":      num_combos,
      "train_samples":            len(train_pairs),
      "test_samples":             len(test_pairs),
      "num_classes":              len(label_list),
      "epochs":                   epochs,
      "batch_size":               batch_size,
      "max_seq_len":              max_seq_len,
      "lr":                       lr,
      "training_time_min":        round(train_secs / 60, 2),
    },
    "metrics": {
      "test_accuracy":     round(float(metrics["eval_accuracy"]),    4),
      "test_f1_macro":     round(float(metrics["eval_f1_macro"]),    4),
      "test_f1_weighted":  round(float(metrics["eval_f1_weighted"]), 4),
      "test_correct":      correct,
      "test_total":        int(len(true)),
    },
    "top10_classes_by_volume": [
      {"label": lbl, "count": c} for lbl, c in top_classes
    ],
    "super_category_for_each_subclass": {
      lbl: short_to_super.get(lbl, "Unknown / Other")
      for lbl in label_list
    },
  }
  with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

  with open(output_dir / "classification_report.txt", "w", encoding="utf-8") as f:
    f.write(f"WangchanBERTa v2 (MERGED) — {model_name}\n")
    f.write(f"Device: {summary['device']}\n")
    f.write(f"Train: {len(train_pairs):,}  Test: {len(test_pairs):,}  Classes: {len(label_list)}\n")
    f.write(f"Epochs: {epochs}  Batch: {batch_size}  LR: {lr}  MaxSeq: {max_seq_len}\n\n")
    f.write(f"Test Accuracy  : {summary['metrics']['test_accuracy']:.4f}\n")
    f.write(f"Test F1 (macro): {summary['metrics']['test_f1_macro']:.4f}\n")
    f.write(f"Test F1 (weighted): {summary['metrics']['test_f1_weighted']:.4f}\n\n")
    f.write(report)

  print()
  print("=" * 70)
  print("DONE")
  print("=" * 70)
  print(f"  Model saved to  : {output_dir}/")
  print(f"  Summary         : {output_dir / 'summary.json'}")
  print(f"  Full report     : {output_dir / 'classification_report.txt'}")
  print(f"  Super-categories: {output_dir / 'super_category_map.json'}")
  print(f"  Test accuracy   : {summary['metrics']['test_accuracy']:.4f}")
  print(f"  Test F1 (macro) : {summary['metrics']['test_f1_macro']:.4f}")
  print(f"  Training time   : {summary['training']['training_time_min']} min")
  print(f"  Improvement vs v1 (71 cls):")
  print(f"    accuracy: 0.8199 -> {summary['metrics']['test_accuracy']:.4f}")
  print(f"    f1_macro: 0.7909 -> {summary['metrics']['test_f1_macro']:.4f}")


if __name__ == "__main__":
  run()
