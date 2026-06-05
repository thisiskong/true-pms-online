"""Predict and batch-classify tickets using the trained WangchanBERTa v2 model.

Usage:
  uv run python predict_wangchanberta_v2.py \
    --input tickets.jsonl \
    --output tickets_predicted_v2.jsonl \
    --model-dir wangchanberta_classifier_v2

To predict one ticket:
  uv run python predict_wangchanberta_v2.py \
    --faulttype "..." \
    --subcategory "..." \
    --faultcause "..."
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

BASE = Path(__file__).parent


def _combo_key(faulttype: str | None, subcategory: str | None, faultcause: str | None) -> tuple[str, str, str]:
    return (
        (faulttype   or "").strip(),
        (subcategory or "").strip(),
        (faultcause  or "").strip(),
    )


def _text_from_ticket(ticket: dict) -> str:
    parts = [
        ticket.get("faulttype", ""),
        ticket.get("subcategory", ""),
        ticket.get("faultcause", ""),
        ticket.get("networkdisp", ""),
        ticket.get("l1name", ""),
    ]
    text = " | ".join(p.strip() for p in parts if p and p.strip())
    return text if text else "unknown"


class WangchanBERTaV2Predictor:
    def __init__(
        self,
        model_dir: str | Path = "wangchanberta_classifier_v2",
        max_seq_len: int = 96,
        device: str | None = None,
    ):
        self.model_dir = BASE / str(model_dir)
        self.max_seq_len = max_seq_len
        self.device = device or ("cuda" if self._cuda_available() else "cpu")
        self._tokenizer = None
        self._model = None
        self._id2label = None
        self._super_category_map = None

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except Exception:
            return False

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        if not self.model_dir.exists():
            raise FileNotFoundError(f"Model directory not found: {self.model_dir}")

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise ImportError("transformers is required to run v2 prediction") from exc

        self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
        self._model = AutoModelForSequenceClassification.from_pretrained(str(self.model_dir))
        self._model.to(self.device)
        self._model.eval()

        with open(self.model_dir / "id2label.json", encoding="utf-8") as f:
            self._id2label = json.load(f)

        self._super_category_map = {}
        super_path = self.model_dir / "super_category_map.json"
        if super_path.exists():
            with open(super_path, encoding="utf-8") as f:
                self._super_category_map = json.load(f).get("short_to_super", {})

    def predict_texts(self, texts: list[str]) -> list[dict]:
        self._ensure_loaded()
        import torch

        enc = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.max_seq_len,
            return_tensors="pt",
        )
        enc = {k: v.to(self.device) for k, v in enc.items()}

        with torch.no_grad():
            logits = self._model(**enc).logits
            probs = torch.softmax(logits, dim=-1)
            scores, pred_ids = torch.max(probs, dim=-1)
            pred_ids = pred_ids.cpu().tolist()
            scores = scores.cpu().tolist()

        results = []
        for pred_id, score in zip(pred_ids, scores):
            label = self._id2label[str(pred_id)]
            results.append({
                "predicted_label_id": pred_id,
                "predicted_label": label,
                "predicted_score": float(score),
                "predicted_super_category": self._super_category_map.get(label, "Unknown / Other"),
            })
        return results

    def predict_ticket(self, ticket: dict) -> dict:
        text = _text_from_ticket(ticket)
        prediction = self.predict_texts([text])[0]
        return {**ticket, **prediction}


def classify_file(
    input_path: Path,
    output_path: Path,
    predictor: WangchanBERTaV2Predictor,
    batch_size: int = 64,
    max_tickets: int | None = None,
) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    batch: list[dict] = []
    texts: list[str] = []

    def write_batch(preds: list[dict]) -> None:
        nonlocal total
        with output_path.open("a", encoding="utf-8") as out_f:
            for item in preds:
                out_f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
                total += 1

    if output_path.exists():
        output_path.unlink()

    print(f"Reading from {input_path} and writing to {output_path}")
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            ticket = json.loads(line)
            batch.append(ticket)
            texts.append(_text_from_ticket(ticket))

            if len(batch) >= batch_size:
                preds = predictor.predict_texts(texts)
                write_batch([{
                    **ticket,
                    **pred,
                } for ticket, pred in zip(batch, preds)])
                print(f"  wrote {total:,} tickets")
                batch.clear()
                texts.clear()

            if max_tickets is not None and total >= max_tickets:
                break

    if batch:
        preds = predictor.predict_texts(texts)
        write_batch([{
            **ticket,
            **pred,
        } for ticket, pred in zip(batch, preds)])
        print(f"  wrote {total:,} tickets")

    print(f"\nDone. Wrote {total:,} tickets to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Predict tickets using WangchanBERTa v2")
    parser.add_argument("--model-dir", default=os.getenv("MODEL_DIR", "wangchanberta_classifier_v2"))
    parser.add_argument("--input", default=os.getenv("INPUT_FILE", "tickets.jsonl"))
    parser.add_argument("--output", default=os.getenv("OUTPUT_FILE", "tickets_predicted_v2.jsonl"))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("BATCH_SIZE", "64")))
    parser.add_argument("--max-seq-len", type=int, default=int(os.getenv("MAX_SEQ_LEN", "96")))
    parser.add_argument("--max-tickets", type=int, default=None)
    parser.add_argument("--faulttype", default=None)
    parser.add_argument("--subcategory", default=None)
    parser.add_argument("--faultcause", default=None)
    args = parser.parse_args()

    predictor = WangchanBERTaV2Predictor(
        model_dir=args.model_dir,
        max_seq_len=args.max_seq_len,
    )

    if args.faulttype is not None or args.subcategory is not None or args.faultcause is not None:
        ticket = {
            "faulttype": args.faulttype,
            "subcategory": args.subcategory,
            "faultcause": args.faultcause,
        }
        result = predictor.predict_ticket(ticket)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    classify_file(
        input_path=BASE / args.input,
        output_path=BASE / args.output,
        predictor=predictor,
        batch_size=args.batch_size,
        max_tickets=args.max_tickets,
    )


if __name__ == "__main__":
    main()
