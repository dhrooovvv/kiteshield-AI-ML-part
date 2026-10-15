"""Benchmark KiteShield rules, Horizon, and their conservative combination."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
for path in (PROJECT_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DATASET_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_test_v2.jsonl"


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


def calculate_metrics(counts: Counts) -> dict[str, float | int]:
    precision = _rate(counts.true_positive, counts.true_positive + counts.false_positive)
    recall = _rate(counts.true_positive, counts.true_positive + counts.false_negative)
    return {
        "count": counts.true_positive
        + counts.false_positive
        + counts.true_negative
        + counts.false_negative,
        "true_positive": counts.true_positive,
        "false_positive": counts.false_positive,
        "true_negative": counts.true_negative,
        "false_negative": counts.false_negative,
        "precision": precision,
        "recall": recall,
        "f1": _rate(2 * precision * recall, precision + recall),
        "false_positive_rate": _rate(
            counts.false_positive, counts.false_positive + counts.true_negative
        ),
        "false_negative_rate": _rate(
            counts.false_negative, counts.false_negative + counts.true_positive
        ),
    }


def percentile(values: list[float], percentage: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentage * len(ordered)) - 1))
    return ordered[index]


def report_predictions(
    records: list[dict[str, str]],
    predictions: list[bool],
    latencies_ms: list[float],
    model_load_ms: float = 0.0,
) -> dict[str, Any]:
    dimensions = {
        "category": "category",
        "language": "language",
        "difficulty": "difficulty",
    }
    aggregate = Counts()
    grouped = {
        dimension: {} for dimension in dimensions
    }
    for record, predicted in zip(records, predictions, strict=True):
        actual = record["label"] != "BENIGN"
        aggregate = aggregate.add(actual, predicted)
        for dimension, field in dimensions.items():
            key = record[field]
            current = grouped[dimension].get(key, Counts())
            grouped[dimension][key] = current.add(actual, predicted)
    return {
        "metrics": calculate_metrics(aggregate),
        "by_category": {
            key: calculate_metrics(value) for key, value in sorted(grouped["category"].items())
        },
        "by_language": {
            key: calculate_metrics(value) for key, value in sorted(grouped["language"].items())
        },
        "by_difficulty": {
            key: calculate_metrics(value)
            for key, value in sorted(grouped["difficulty"].items())
        },
        "latency_ms": {
            "mean": statistics.mean(latencies_ms) if latencies_ms else 0.0,
            "median": statistics.median(latencies_ms) if latencies_ms else 0.0,
            "p95": percentile(latencies_ms, 0.95),
            "model_load": model_load_ms,
        },
    }


def run_rules(records: list[dict[str, str]]) -> tuple[list[bool], list[float]]:
    from app.ai_ml import InjectionScreen

    detector = InjectionScreen()
    predictions: list[bool] = []
    latencies_ms: list[float] = []
    for record in records:
        started_ns = time.perf_counter_ns()
        result = detector.screen(record["text"])
        latencies_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
        predictions.append(result.label.value != "BENIGN")
    return predictions, latencies_ms


def run_horizon(
    records: list[dict[str, str]],
) -> tuple[list[bool], list[float], float, dict[int, str]]:
    import torch
    from benchmark_horizon_guard import load_classifier

    started_ns = time.perf_counter_ns()
    tokenizer, model, id2label, device = load_classifier()
    model_load_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    injection_id = next(key for key, value in id2label.items() if value == "INJECTION")
    predictions: list[bool] = []
    latencies_ms: list[float] = []
    with torch.inference_mode():
        for record in records:
            started_ns = time.perf_counter_ns()
            inputs = tokenizer(
                record["text"],
                return_tensors="pt",
                truncation=True,
                max_length=512,
            )
            inputs = {name: value.to(device) for name, value in inputs.items()}
            logits = model(**inputs).logits
            latencies_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
            predictions.append(int(torch.argmax(logits, dim=-1).item()) == injection_id)
    return predictions, latencies_ms, model_load_ms, id2label


def print_metrics(name: str, report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    latency = report["latency_ms"]
    print(name)
    print(
        "  precision={precision:.4f} recall={recall:.4f} f1={f1:.4f} "
        "fpr={false_positive_rate:.4f} fnr={false_negative_rate:.4f}".format(**metrics)
    )
    print(
        f"  confusion_matrix=TP:{metrics['true_positive']} FP:{metrics['false_positive']} "
        f"TN:{metrics['true_negative']} FN:{metrics['false_negative']}"
    )
    print(
        f"  latency_ms=mean:{latency['mean']:.3f} median:{latency['median']:.3f} "
        f"p95:{latency['p95']:.3f} model_load:{latency['model_load']:.3f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    try:
        from generate_evaluation_v2 import load_records

        records = load_records(args.dataset)
        rule_predictions, rule_latencies = run_rules(records)
        output: dict[str, Any] = {
            "dataset": args.dataset.name,
            "records": len(records),
            "rules_only": report_predictions(records, rule_predictions, rule_latencies),
            "configuration": {
                "rules": "InjectionScreen rules-v1, unchanged",
                "combined": "rules OR Horizon INJECTION",
            },
        }
        if not args.rules_only:
            horizon_predictions, horizon_latencies, load_ms, id2label = run_horizon(records)
            combined_predictions = [
                rule or horizon
                for rule, horizon in zip(rule_predictions, horizon_predictions, strict=True)
            ]
            output["horizon_only"] = report_predictions(
                records, horizon_predictions, horizon_latencies, load_ms
            )
            output["combined"] = report_predictions(
                records,
                combined_predictions,
                [
                    rule + horizon
                    for rule, horizon in zip(rule_latencies, horizon_latencies, strict=True)
                ],
                load_ms,
            )
            output["configuration"]["horizon"] = {
                "model": "Horizon-Labs/prompt-injection-guard-base",
                "id2label": id2label,
                "decision": "argmax(logits)",
                "explicit_threshold": None,
            }
    except Exception as exc:
        print(f"Evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        serialized = json.dumps(output, indent=2, sort_keys=True)
        print(serialized)
        if args.json_output:
            args.json_output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(f"Dataset: {output['dataset']} ({output['records']} records)")
        print_metrics("Rules only", output["rules_only"])
        if "horizon_only" in output:
            print_metrics("Horizon only", output["horizon_only"])
            print_metrics("Combined rules + Horizon", output["combined"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
