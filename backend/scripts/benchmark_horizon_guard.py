"""Benchmark Horizon-Labs/prompt-injection-guard-base locally."""

from __future__ import annotations

import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MODEL_ID = "Horizon-Labs/prompt-injection-guard-base"
DATASET_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_dataset_v1.jsonl"


@dataclass(frozen=True)
class Counts:
    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0

    def add(self, actual_positive: bool, predicted_positive: bool) -> Counts:
        if actual_positive and predicted_positive:
            return Counts(
                self.true_positive + 1,
                self.false_positive,
                self.true_negative,
                self.false_negative,
            )
        if not actual_positive and predicted_positive:
            return Counts(
                self.true_positive,
                self.false_positive + 1,
                self.true_negative,
                self.false_negative,
            )
        if not actual_positive and not predicted_positive:
            return Counts(
                self.true_positive,
                self.false_positive,
                self.true_negative + 1,
                self.false_negative,
            )
        return Counts(
            self.true_positive,
            self.false_positive,
            self.true_negative,
            self.false_negative + 1,
        )


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def metrics(counts: Counts) -> dict[str, float | int]:
    precision = _rate(counts.true_positive, counts.true_positive + counts.false_positive)
    recall = _rate(counts.true_positive, counts.true_positive + counts.false_negative)
    return {
        "precision": precision,
        "recall": recall,
        "f1": _rate(2 * precision * recall, precision + recall),
        "false_positive_rate": _rate(
            counts.false_positive, counts.false_positive + counts.true_negative
        ),
        "false_negative_rate": _rate(
            counts.false_negative, counts.false_negative + counts.true_positive
        ),
        "true_positive": counts.true_positive,
        "false_positive": counts.false_positive,
        "true_negative": counts.true_negative,
        "false_negative": counts.false_negative,
    }


def load_classifier() -> tuple[Any, Any, dict[int, str], torch.device]:
    """Load the configured model and tokenizer without changing dependencies."""
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_ID)
    model.eval()
    device = torch.device("cpu")
    model.to(device)
    id2label = {int(key): value.upper() for key, value in model.config.id2label.items()}
    if set(id2label.values()) != {"SAFE", "INJECTION"}:
        raise RuntimeError(f"Unexpected model labels: {id2label}")
    return tokenizer, model, id2label, device


def evaluate_classifier(
    records: list[dict[str, str]],
) -> tuple[Counts, list[float], dict[int, str]]:
    from app.ai_ml import InjectionLabel

    tokenizer, model, id2label, device = load_classifier()
    injection_id = next(key for key, value in id2label.items() if value == "INJECTION")
    counts = Counts()
    latencies_ms: list[float] = []

    with torch.inference_mode():
        for record in records:
            inputs = tokenizer(
                record["text"],
                return_tensors="pt",
                truncation=True,
                max_length=512,
            )
            inputs = {name: value.to(device) for name, value in inputs.items()}
            started_ns = time.perf_counter_ns()
            logits = model(**inputs).logits
            elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
            probabilities = torch.softmax(logits, dim=-1)[0]
            predicted_id = int(torch.argmax(probabilities).item())
            actual_positive = record["label"] != InjectionLabel.BENIGN.value
            counts = counts.add(actual_positive, predicted_id == injection_id)
            latencies_ms.append(elapsed_ms)

    return counts, latencies_ms, id2label


def print_metrics(name: str, values: dict[str, float | int]) -> None:
    print(name)
    for metric_name in (
        "precision",
        "recall",
        "f1",
        "false_positive_rate",
        "false_negative_rate",
    ):
        print(f"  {metric_name}: {values[metric_name]:.4f}")
    print(
        "  confusion_matrix: "
        f"TP={values['true_positive']} FP={values['false_positive']} "
        f"TN={values['true_negative']} FN={values['false_negative']}"
    )


def main() -> int:
    from evaluate_injection_screen import evaluate, load_dataset

    try:
        records = load_dataset(DATASET_PATH)
        counts, latencies_ms, id2label = evaluate_classifier(records)
    except Exception as exc:
        print(f"Prompt Guard benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    rules_report = evaluate(records)["aggregate"]
    classifier_report = metrics(counts)
    print(f"Model: {MODEL_ID}")
    print(f"Dataset: {DATASET_PATH.name} ({len(records)} records)")
    print(f"Label mapping: {id2label}")
    print("Decision rule: argmax(logits); explicit threshold: not configured")
    print(
        f"Inference latency (CPU, model call only): mean={statistics.mean(latencies_ms):.3f} ms "
        f"median={statistics.median(latencies_ms):.3f} ms"
    )
    print()
    print_metrics("Prompt Guard classifier-only", classifier_report)
    print()
    print_metrics("KiteShield rules-only", rules_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
