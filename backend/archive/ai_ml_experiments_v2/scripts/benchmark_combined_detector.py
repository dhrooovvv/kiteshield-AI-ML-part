"""Compare KiteShield rules, Horizon Guard, and conservative OR detection."""

from __future__ import annotations

import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
for path in (PROJECT_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

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
    from benchmark_horizon_guard import MODEL_ID, load_classifier
    from evaluate_injection_screen import load_dataset

    from app.ai_ml import InjectionLabel, InjectionScreen

    try:
        records = load_dataset(DATASET_PATH)
        tokenizer, model, id2label, device = load_classifier()
        injection_id = next(key for key, value in id2label.items() if value == "INJECTION")
        rules = InjectionScreen()
        counts = {name: Counts() for name in ("rules", "horizon", "combined")}
        latencies_ms = {name: [] for name in counts}

        with torch.inference_mode():
            for record in records:
                actual_positive = record["label"] != InjectionLabel.BENIGN.value

                rules_started = time.perf_counter_ns()
                rule_result = rules.screen(record["text"])
                rules_elapsed = (time.perf_counter_ns() - rules_started) / 1_000_000
                rules_positive = rule_result.label != InjectionLabel.BENIGN

                horizon_started = time.perf_counter_ns()
                inputs = tokenizer(
                    record["text"],
                    return_tensors="pt",
                    truncation=True,
                    max_length=512,
                )
                inputs = {name: value.to(device) for name, value in inputs.items()}
                logits = model(**inputs).logits
                horizon_elapsed = (time.perf_counter_ns() - horizon_started) / 1_000_000
                horizon_positive = int(torch.argmax(logits, dim=-1).item()) == injection_id

                combined_positive = rules_positive or horizon_positive
                counts["rules"] = counts["rules"].add(actual_positive, rules_positive)
                counts["horizon"] = counts["horizon"].add(actual_positive, horizon_positive)
                counts["combined"] = counts["combined"].add(actual_positive, combined_positive)
                latencies_ms["rules"].append(rules_elapsed)
                latencies_ms["horizon"].append(horizon_elapsed)
                latencies_ms["combined"].append(rules_elapsed + horizon_elapsed)
    except Exception as exc:
        print(f"Combined benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Model: {MODEL_ID}")
    print(f"Dataset: {DATASET_PATH.name} ({len(records)} records)")
    print(f"Label mapping: {id2label}")
    print("Classifier decision rule: argmax(logits); explicit threshold: not configured")
    print("Combined policy: flag if rules OR Horizon predicts INJECTION")
    print()
    for name, label in (
        ("rules", "Rules only"),
        ("horizon", "Horizon only"),
        ("combined", "Combined rules + Horizon"),
    ):
        print_metrics(label, metrics(counts[name]))
        print(
            f"  latency_ms: mean={statistics.mean(latencies_ms[name]):.3f} "
            f"median={statistics.median(latencies_ms[name]):.3f}"
        )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
