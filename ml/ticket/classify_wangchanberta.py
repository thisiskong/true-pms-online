"""
Classify tickets with WangchanBERTa (Thai-specific BERT, aairesrch).

Strategy:
  - Uses cluster_label from cluster_mapping.json as the prediction target
    (joins tickets.jsonl with cluster_mapping.json via the
     (faulttype, subcategory, faultcause) combo key)
  - Text is built from: faulttype | subcategory | faultcause | networkdisp | l1name
  - Fine-tunes airesearch/wangchanberta-base-att-spm-uncased
  - Saves the trained model + tokenizer + a classification_report + summary

Usage:
  uv run python classify_wangchanberta.py

.env keys:
  HF_TOKEN          -- Hugging Face token (required for gated models)
  INPUT_FILE        -- default: tickets.jsonl
  MAPPING_FILE      -- default: cluster_mapping.json
  OUTPUT_DIR        -- default: wangchanberta_classifier
  WANGCHAN_MODEL    -- default: airesearch/wangchanberta-base-att-spm-uncased
  MAX_TRAIN_SAMPLES -- default: 30000  (cap for speed on CPU)
  MAX_TEST_SAMPLES  -- default: 3000
  MAX_SEQ_LEN       -- default: 96
  BATCH_SIZE        -- default: 16
  EPOCHS            -- default: 2
  LR                -- default: 3e-5
  TEST_SPLIT        -- default: 0.1
  SEED              -- default: 42
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


# -----------------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------------

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


def load_labeled_data() -> tuple[list[tuple[str, str]], int, int]:
  """Join tickets with cluster_mapping and return (text, label) pairs.

  Returns (pairs, num_combos, total_scanned).
  """
  input_file   = BASE / os.getenv("INPUT_FILE",   "tickets.jsonl")
  mapping_file = BASE / os.getenv("MAPPING_FILE", "cluster_mapping.json")

  if not input_file.exists():
    raise FileNotFoundError(f"{input_file} not found. Run load_tickets.py first.")
  if not mapping_file.exists():
    raise FileNotFoundError(f"{mapping_file} not found. Run embed_cluster.py first.")

  print(f"Loading mapping {mapping_file.name} ...")
  with open(mapping_file, encoding="utf-8") as f:
    mapping_entries = json.load(f)

  combo_to_label: dict[tuple, str] = {}
  for e in mapping_entries:
    key = (e["faulttype"], e["subcategory"], e["faultcause"])
    combo_to_label[key] = e["cluster_label"]
  print(f"  {len(combo_to_label):,} distinct combos loaded")

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
      label = combo_to_label.get(key)
      if not label:
        continue
      text = _text_from_ticket(t)
      if not text:
        continue
      pairs.append((text, label))
      if (i + 1) % 100_000 == 0:
        print(f"  ... {i+1:,} tickets scanned, {len(pairs):,} labeled")

  print(f"  {len(pairs):,} labeled tickets collected")
  return pairs, len(combo_to_label), total_scanned


# -----------------------------------------------------------------------
# Sampling (balance classes + cap total)
# -----------------------------------------------------------------------

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

  # cap per-class proportionally, but keep min_per_class
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


# -----------------------------------------------------------------------
# Training & evaluation
# -----------------------------------------------------------------------

def run() -> None:
  output_dir   = BASE / os.getenv("OUTPUT_DIR",     "wangchanberta_classifier")
  model_name   = os.getenv("WANGCHAN_MODEL",
                           "airesearch/wangchanberta-base-att-spm-uncased")
  max_train    = int(os.getenv("MAX_TRAIN_SAMPLES", 30000))
  max_test     = int(os.getenv("MAX_TEST_SAMPLES",  3000))
  max_seq_len  = int(os.getenv("MAX_SEQ_LEN",       96))
  batch_size   = int(os.getenv("BATCH_SIZE",        16))
  epochs       = int(os.getenv("EPOCHS",            2))
  lr           = float(os.getenv("LR",              3e-5))
  test_split   = float(os.getenv("TEST_SPLIT",      0.1))
  hf_token     = os.getenv("HF_TOKEN") or None

  output_dir.mkdir(exist_ok=True)
  print("=" * 70)
  print("WangchanBERTa Ticket Classifier")
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
  print("[1/5] Loading & labeling tickets ...")
  pairs, num_combos, total_scanned = load_labeled_data()

  print("\n[2/5] Sampling ...")
  sampled = balance_sample(pairs, max_total=max_train + max_test)
  del pairs

  # train / test split
  n_test = min(max_test, max(1, int(len(sampled) * test_split)))
  n_test = min(n_test, len(sampled) // 2)
  test_pairs  = sampled[:n_test]
  train_pairs = sampled[n_test:]
  print(f"  train: {len(train_pairs):,}  test: {len(test_pairs):,}")

  # label encoding
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

  # ----- final evaluation -----
  print("\nEvaluating on test set ...")
  metrics = trainer.evaluate()
  print(f"  test accuracy : {metrics['eval_accuracy']:.4f}")
  print(f"  test f1_macro : {metrics['eval_f1_macro']:.4f}")
  print(f"  test f1_weight: {metrics['eval_f1_weighted']:.4f}")

  # predictions for classification report
  pred_output = trainer.predict(test_ds)
  preds = np.argmax(pred_output.predictions, axis=-1)
  true  = pred_output.label_ids

  from sklearn.metrics import classification_report
  # truncate class names for readable report
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

  # save artifacts
  print(f"\nSaving model to {output_dir}/ ...")
  trainer.save_model(str(output_dir))
  tokenizer.save_pretrained(str(output_dir))

  # save id maps
  with open(output_dir / "label2id.json", "w", encoding="utf-8") as f:
    json.dump(label2id, f, ensure_ascii=False, indent=2)
  with open(output_dir / "id2label.json", "w", encoding="utf-8") as f:
    json.dump(id2label, f, ensure_ascii=False, indent=2)

  # ----- summary report -----
  label_counter = Counter(lbl for _, lbl in train_pairs + test_pairs)
  top_classes = label_counter.most_common(10)
  pred_counter = Counter(int(p) for p in preds)
  correct = int((preds == true).sum())

  summary = {
    "model": model_name,
    "device": "cuda" if torch.cuda.is_available() else "cpu",
    "input_file": str(input_file.name) if (input_file := BASE / os.getenv("INPUT_FILE", "tickets.jsonl")) else "",
    "mapping_file": str(mapping_file.name) if (mapping_file := BASE / os.getenv("MAPPING_FILE", "cluster_mapping.json")) else "",
    "training": {
      "total_tickets_scanned": total_scanned,
      "total_labeled_tickets_available": num_combos,
      "train_samples": len(train_pairs),
      "test_samples": len(test_pairs),
      "num_classes": len(label_list),
      "epochs": epochs,
      "batch_size": batch_size,
      "max_seq_len": max_seq_len,
      "lr": lr,
      "training_time_min": round(train_secs / 60, 2),
    },
    "metrics": {
      "test_accuracy": round(float(metrics["eval_accuracy"]), 4),
      "test_f1_macro": round(float(metrics["eval_f1_macro"]), 4),
      "test_f1_weighted": round(float(metrics["eval_f1_weighted"]), 4),
      "test_correct": correct,
      "test_total": int(len(true)),
    },
    "top10_classes_by_volume": [
      {"label": lbl, "count": c} for lbl, c in top_classes
    ],
    "prediction_distribution_top10": [
      {"label": id2label[i], "count": pred_counter.get(i, 0)}
      for i, _ in [(i, c) for i, c in enumerate([0]*10)]  # placeholder
    ],
  }
  # fix prediction distribution
  summary["prediction_distribution_top10"] = [
    {"label": id2label[i], "count": pred_counter.get(i, 0)}
    for i, _ in sorted(enumerate(label_list), key=lambda kv: -pred_counter.get(kv[0], 0))[:10]
  ]

  with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

  with open(output_dir / "classification_report.txt", "w", encoding="utf-8") as f:
    f.write(f"WangchanBERTa Ticket Classifier — {model_name}\n")
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
  print(f"  Test accuracy   : {summary['metrics']['test_accuracy']:.4f}")
  print(f"  Test F1 (macro) : {summary['metrics']['test_f1_macro']:.4f}")
  print(f"  Training time   : {summary['training']['training_time_min']} min")


if __name__ == "__main__":
  run()
