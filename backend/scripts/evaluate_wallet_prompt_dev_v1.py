"""Evaluate the wallet-specific prompt-injection development dataset.

This is an evaluation artifact only. It does not alter production settings or
screening behavior and uses the existing detector implementations.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = BACKEND_ROOT / "app" / "ai_ml" / "wallet_prompt_dev_v1.jsonl"
REPORT_DIR = BACKEND_ROOT / "reports"
RESULT_JSON = REPORT_DIR / "wallet_prompt_dev_v1_results.json"
RESULT_MD = REPORT_DIR / "wallet_prompt_dev_v1_results.md"
BASTION_THRESHOLD = 0.059

for path in (BACKEND_ROOT, BACKEND_ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def load_records() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def metrics(records: list[dict[str, Any]], predictions: list[bool]) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    for record, prediction in zip(records, predictions, strict=True):
        actual = record["label"] != "BENIGN"
        if actual and prediction:
            tp += 1
        elif not actual and prediction:
            fp += 1
        elif actual:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "count": len(records),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "false_negative_rate": fn / (fn + tp) if fn + tp else 0.0,
    }


def by_category(records: list[dict[str, Any]], predictions: list[bool]) -> dict[str, Any]:
    groups: dict[str, tuple[list[dict[str, Any]], list[bool]]] = defaultdict(lambda: ([], []))
    for record, prediction in zip(records, predictions, strict=True):
        groups[record["category"]][0].append(record)
        groups[record["category"]][1].append(prediction)
    return {name: metrics(*group) for name, group in sorted(groups.items())}


def latency_stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return {
        "mean_ms": statistics.mean(values) if values else 0.0,
        "median_ms": statistics.median(values) if values else 0.0,
        "p95_ms": ordered[index] if ordered else 0.0,
    }


def error_examples(
    records: list[dict[str, Any]],
    predictions: list[bool],
    scores: list[float],
) -> list[dict[str, Any]]:
    errors = []
    for record, prediction, score in zip(records, predictions, scores, strict=True):
        actual = record["label"] != "BENIGN"
        if actual != prediction:
            errors.append(
                {
                    "id": record["id"],
                    "label": record["label"],
                    "category": record["category"],
                    "predicted_attack": prediction,
                    "score": score,
                    "text": record["text"],
                }
            )
    return errors


def main() -> None:
    from benchmark_advanced_detection_v2 import run_bastion, run_horizon, run_rules

    records = load_records()
    rules, rules_latency, _ = run_rules(records)
    horizon, horizon_scores, horizon_latency, horizon_load, _, horizon_version = run_horizon(
        records
    )
    bastion_labels, bastion_scores, bastion_latency, bastion_load, bastion_version = run_bastion(
        records
    )
    bastion = [score >= BASTION_THRESHOLD for score in bastion_scores]
    ensemble = [r or h or b for r, h, b in zip(rules, horizon, bastion, strict=True)]

    outputs = {
        "rules_only": {
            "metrics": metrics(records, rules),
            "by_category": by_category(records, rules),
            "latency": latency_stats(rules_latency),
        },
        "horizon_only": {
            "metrics": metrics(records, horizon),
            "by_category": by_category(records, horizon),
            "latency": latency_stats(horizon_latency),
            "model_load_ms": horizon_load,
            "model_version": horizon_version,
        },
        "bastion_only": {
            "metrics": metrics(records, bastion),
            "by_category": by_category(records, bastion),
            "latency": latency_stats(bastion_latency),
            "model_load_ms": bastion_load,
            "model_version": bastion_version,
            "threshold": BASTION_THRESHOLD,
            "package_label_attack_count": sum(bastion_labels),
        },
        "three_layer_or": {
            "metrics": metrics(records, ensemble),
            "by_category": by_category(records, ensemble),
            "detector_disagreement": {
                "rules_vs_horizon": sum(r != h for r, h in zip(rules, horizon, strict=True)),
                "rules_vs_bastion": sum(r != b for r, b in zip(rules, bastion, strict=True)),
                "horizon_vs_bastion": sum(h != b for h, b in zip(horizon, bastion, strict=True)),
                "all_three_disagree": sum(
                    len({r, h, b}) == 2 for r, h, b in zip(rules, horizon, bastion, strict=True)
                ),
            },
        },
    }
    report = {
        "dataset": str(DATASET_PATH),
        "synthetic": True,
        "records": len(records),
        "label_mapping": {"BENIGN": False, "MALICIOUS": True},
        "decision_policy": "rules OR horizon OR bastion",
        "detectors": outputs,
        "errors": {
            "rules_only": error_examples(records, rules, [0.0] * len(records)),
            "horizon_only": error_examples(records, horizon, horizon_scores),
            "bastion_only": error_examples(records, bastion, bastion_scores),
            "three_layer_or": error_examples(records, ensemble, [0.0] * len(records)),
        },
        "limitations": [
            "Small synthetic wallet-specific development set; not a production benchmark.",
            "Threshold was not selected or tuned by this script.",
            "The OR policy propagates any individual detector false positive.",
        ],
    }
    REPORT_DIR.mkdir(exist_ok=True)
    RESULT_JSON.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# Wallet prompt screening development evaluation",
        "",
        f"Dataset: `{DATASET_PATH}` ({len(records)} synthetic examples)",
        f"Bastion threshold: `{BASTION_THRESHOLD}`; ensemble: `Rules OR Horizon OR Bastion`.",
        "",
        "| Strategy | TP | FP | TN | FN | Precision | Recall | F1 | FPR | FNR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, value in outputs.items():
        m = value["metrics"]
        lines.append(
            f"| {name} | {m['tp']} | {m['fp']} | {m['tn']} | {m['fn']} | "
            f"{m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | "
            f"{m['false_positive_rate']:.3f} | {m['false_negative_rate']:.3f} |"
        )
    lines.extend(
        ["", "Results are synthetic development evidence and do not establish real-world security."]
    )
    RESULT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({name: value["metrics"] for name, value in outputs.items()}, indent=2))
    print(f"Wrote {RESULT_JSON}")
    print(f"Wrote {RESULT_MD}")


if __name__ == "__main__":
    main()
