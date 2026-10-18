"""Evaluate the deterministic prompt-injection screen on a JSONL dataset.

This script intentionally uses only the Python standard library. It maps
BENIGN to the negative class and SUSPICIOUS/MALICIOUS to the positive class.
The detector remains advisory; these metrics do not authorize transactions.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai_ml import InjectionLabel, InjectionScreen  # noqa: E402

DATASET_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_dataset_v1.jsonl"
REQUIRED_FIELDS = {"id", "text", "label", "attack_category", "explanation"}
VALID_LABELS = {label.value for label in InjectionLabel}


@dataclass(frozen=True)
class Counts:
    """Binary classification confusion-matrix counts."""

    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0

    def add(self, *, actual_positive: bool, predicted_positive: bool) -> Counts:
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

    @property
    def total(self) -> int:
        return (
            self.true_positive
            + self.false_positive
            + self.true_negative
            + self.false_negative
        )


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def metrics(counts: Counts) -> dict[str, Any]:
    """Calculate deterministic binary metrics from confusion-matrix counts."""
    precision = _rate(counts.true_positive, counts.true_positive + counts.false_positive)
    recall = _rate(counts.true_positive, counts.true_positive + counts.false_negative)
    f1 = _rate(2 * precision * recall, precision + recall)
    return {
        "count": counts.total,
        "true_positive": counts.true_positive,
        "false_positive": counts.false_positive,
        "true_negative": counts.true_negative,
        "false_negative": counts.false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": _rate(
            counts.false_positive, counts.false_positive + counts.true_negative
        ),
        "false_negative_rate": _rate(
            counts.false_negative, counts.false_negative + counts.true_positive
        ),
    }


def load_dataset(path: Path) -> list[dict[str, str]]:
    """Load and validate the versioned JSONL dataset."""
    records: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at line {line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"Dataset line {line_number} must contain a JSON object")
        missing = REQUIRED_FIELDS - record.keys()
        if missing:
            raise ValueError(f"Dataset line {line_number} is missing fields: {sorted(missing)}")
        if any(
            not isinstance(record[field], str) or not record[field].strip()
            for field in REQUIRED_FIELDS
        ):
            raise ValueError(f"Dataset line {line_number} has an empty or non-string field")
        if record["id"] in seen_ids:
            raise ValueError(f"Duplicate dataset id: {record['id']}")
        if record["label"] not in VALID_LABELS:
            raise ValueError(f"Unsupported label at line {line_number}: {record['label']}")
        seen_ids.add(record["id"])
        records.append(record)
    if not records:
        raise ValueError("Dataset is empty")
    return records


def evaluate(records: list[dict[str, str]]) -> dict[str, Any]:
    """Run InjectionScreen and return aggregate and category metrics."""
    detector = InjectionScreen()
    aggregate = Counts()
    by_category: dict[str, Counts] = defaultdict(Counts)
    by_label: dict[str, Counts] = defaultdict(Counts)

    for record in records:
        result = detector.screen(record["text"])
        actual_positive = record["label"] != InjectionLabel.BENIGN.value
        predicted_positive = result.label != InjectionLabel.BENIGN
        aggregate = aggregate.add(
            actual_positive=actual_positive,
            predicted_positive=predicted_positive,
        )
        by_category[record["attack_category"]] = by_category[record["attack_category"]].add(
            actual_positive=actual_positive,
            predicted_positive=predicted_positive,
        )
        by_label[record["label"]] = by_label[record["label"]].add(
            actual_positive=actual_positive,
            predicted_positive=predicted_positive,
        )

    return {
        "dataset": "evaluation_dataset_v1.jsonl",
        "records": len(records),
        "positive_labels": [InjectionLabel.SUSPICIOUS.value, InjectionLabel.MALICIOUS.value],
        "aggregate": metrics(aggregate),
        "by_attack_category": {
            category: metrics(by_category[category]) for category in sorted(by_category)
        },
        "by_label": {label: metrics(by_label[label]) for label in sorted(by_label)},
    }


def print_report(report: dict[str, Any]) -> None:
    """Print stable human-readable output."""
    aggregate = report["aggregate"]
    print(f"Dataset: {report['dataset']}")
    print(f"Records: {report['records']}")
    print("Positive class: SUSPICIOUS or MALICIOUS")
    print("\nAggregate metrics")
    for name in (
        "precision",
        "recall",
        "f1",
        "false_positive_rate",
        "false_negative_rate",
    ):
        print(f"  {name}: {aggregate[name]:.4f}")
    print(
        "  confusion_matrix: "
        f"TP={aggregate['true_positive']} FP={aggregate['false_positive']} "
        f"TN={aggregate['true_negative']} FN={aggregate['false_negative']}"
    )
    print("\nMetrics by attack category")
    for category, category_metrics in report["by_attack_category"].items():
        print(
            f"  {category}: n={category_metrics['count']} "
            f"precision={category_metrics['precision']:.4f} "
            f"recall={category_metrics['recall']:.4f} "
            f"f1={category_metrics['f1']:.4f} "
            f"fpr={category_metrics['false_positive_rate']:.4f} "
            f"fnr={category_metrics['false_negative_rate']:.4f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DATASET_PATH,
        help="Path to a compatible JSONL dataset (default: evaluation_dataset_v1.jsonl)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete metrics report as JSON",
    )
    args = parser.parse_args()

    try:
        report = evaluate(load_dataset(args.dataset))
    except (OSError, ValueError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
