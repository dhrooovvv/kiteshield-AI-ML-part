"""Reproducible offline evaluation for Horizon, Bastion, rules, and policies."""

from __future__ import annotations

import json
import math
import os
import platform
import statistics
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
REPORT_DIR = PROJECT_ROOT / "reports"
for path in (PROJECT_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DEV_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_dev_v2.jsonl"
TEST_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_test_v2.jsonl"
RESULT_JSON = REPORT_DIR / "advanced_detection_evaluation_v2.json"
RESULT_MD = REPORT_DIR / "advanced_detection_evaluation_v2.md"
BASTION_THRESHOLD = 0.059
MIN_RECALL = 0.50
MAX_FPR = 0.10
STRATEGY_NAMES = (
    "horizon_only",
    "bastion_only",
    "rules_only",
    "horizon_or_bastion",
    "horizon_and_bastion",
    "horizon_first_risk_based",
    "disagreement_review",
    "three_layer_or",
    "horizon_threshold_bastion",
)


def pkg_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def counts(records: list[dict[str, Any]], predictions: list[bool]) -> dict[str, int]:
    values = {"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0}
    for record, predicted in zip(records, predictions, strict=True):
        actual = record["label"] != "BENIGN"
        if actual and predicted:
            values["true_positive"] += 1
        elif not actual and predicted:
            values["false_positive"] += 1
        elif not actual:
            values["true_negative"] += 1
        else:
            values["false_negative"] += 1
    return values


def metric_values(values: dict[str, int], total: int) -> dict[str, float | int | None]:
    tp = values["true_positive"]
    fp = values["false_positive"]
    tn = values["true_negative"]
    fn = values["false_negative"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else None
    return {
        **values,
        "count": total,
        "accuracy": (tp + tn) / total if total else 0.0,
        "balanced_accuracy": ((recall + specificity) / 2 if specificity is not None else None),
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negative_rate": fn / (fn + tp) if fn + tp else None,
    }


def percentile(values: list[float], percentage: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentage * len(ordered)) - 1))
    return ordered[index]


def grouped(records: list[dict[str, Any]], predictions: list[bool], field: str) -> dict[str, Any]:
    groups: dict[str, tuple[list[dict[str, Any]], list[bool]]] = {}
    for record, prediction in zip(records, predictions, strict=True):
        key = str(record[field])
        if key not in groups:
            groups[key] = ([], [])
        groups[key][0].append(record)
        groups[key][1].append(prediction)
    return {
        key: metric_values(counts(*items), len(items[0])) for key, items in sorted(groups.items())
    }


def make_report(
    records: list[dict[str, Any]],
    predictions: list[bool],
    latencies: list[float],
    model_load_ms: float,
    review_count: int = 0,
    failed: int = 0,
    skipped: int = 0,
    fallback: int = 0,
) -> dict[str, Any]:
    return {
        "metrics": metric_values(counts(records, predictions), len(records)),
        "by_category": grouped(records, predictions, "category"),
        "by_language": grouped(records, predictions, "language"),
        "by_difficulty": grouped(records, predictions, "difficulty"),
        "operational_counts": {
            "total": len(records),
            "benign": sum(record["label"] == "BENIGN" for record in records),
            "attacks": sum(record["label"] != "BENIGN" for record in records),
            "review": review_count,
            "uncertain": 0,
            "inference_failures": failed,
            "skipped": skipped,
            "fallback_predictions": fallback,
        },
        "latency_ms": {
            "mean": statistics.mean(latencies) if latencies else 0.0,
            "median": statistics.median(latencies) if latencies else 0.0,
            "p95": percentile(latencies, 0.95),
            "model_load": model_load_ms,
        },
    }


def run_rules(records: list[dict[str, Any]]) -> tuple[list[bool], list[float], list[Any]]:
    from app.ai_ml import InjectionScreen

    detector = InjectionScreen()
    predictions: list[bool] = []
    latencies: list[float] = []
    outputs: list[Any] = []
    for record in records:
        started_ns = time.perf_counter_ns()
        output = detector.screen(record["text"])
        latencies.append((time.perf_counter_ns() - started_ns) / 1_000_000)
        predictions.append(output.label.value != "BENIGN")
        outputs.append(output)
    return predictions, latencies, outputs


def run_horizon(
    records: list[dict[str, Any]],
) -> tuple[list[bool], list[float], list[float], float, dict[int, str], str]:
    import torch
    from benchmark_horizon_guard import load_classifier

    started_ns = time.perf_counter_ns()
    tokenizer, model, id2label, device = load_classifier()
    load_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    injection_id = next(key for key, value in id2label.items() if value == "INJECTION")
    predictions: list[bool] = []
    scores: list[float] = []
    latencies: list[float] = []
    with torch.inference_mode():
        for record in records:
            inputs = tokenizer(record["text"], return_tensors="pt", truncation=True, max_length=512)
            inputs = {name: value.to(device) for name, value in inputs.items()}
            started_ns = time.perf_counter_ns()
            logits = model(**inputs).logits
            latencies.append((time.perf_counter_ns() - started_ns) / 1_000_000)
            probabilities = torch.softmax(logits, dim=-1)[0]
            predicted_id = int(torch.argmax(probabilities).item())
            predictions.append(predicted_id == injection_id)
            scores.append(float(probabilities[injection_id].item()))
    return predictions, scores, latencies, load_ms, id2label, "horizon-local"


def run_bastion(
    records: list[dict[str, Any]],
) -> tuple[list[bool], list[float], list[float], float, str | None]:
    from bastion_prompt_protection import Guard, Preset

    guard = Guard(preset=Preset.TINY)
    if guard._binary is None:
        raise RuntimeError("Bastion binary stage is disabled")
    started_ns = time.perf_counter_ns()
    if not guard._binary._loader.is_available():
        raise RuntimeError("Bastion model unavailable")
    load_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    predictions: list[bool] = []
    scores: list[float] = []
    latencies: list[float] = []
    for record in records:
        started_ns = time.perf_counter_ns()
        output = guard.protect(record["text"])
        latencies.append((time.perf_counter_ns() - started_ns) / 1_000_000)
        if output.label not in {"safe", "attack"} or not 0.0 <= output.risk <= 1.0:
            raise RuntimeError(f"invalid Bastion output: {output.to_dict()}")
        predictions.append(output.label == "attack")
        scores.append(float(output.risk))
    return predictions, scores, latencies, load_ms, guard.model_version


def threshold_metrics(
    records: list[dict[str, Any]], scores: list[float], threshold: float
) -> dict[str, Any]:
    predictions = [score >= threshold for score in scores]
    return metric_values(counts(records, predictions), len(records))


def horizon_threshold_sweep(records: list[dict[str, Any]], scores: list[float]) -> dict[str, Any]:
    candidates = sorted({0.5, *scores})
    rows = [
        {"threshold": threshold, **threshold_metrics(records, scores, threshold)}
        for threshold in candidates
    ]
    eligible_fpr = [row for row in rows if (row["false_positive_rate"] or 0.0) <= MAX_FPR]
    eligible_recall = [row for row in rows if row["recall"] >= MIN_RECALL]
    return {
        "constraints": {"maximum_dev_fpr": MAX_FPR, "minimum_dev_recall": MIN_RECALL},
        "candidates_evaluated": len(rows),
        "best_highest_recall_under_fpr": max(
            eligible_fpr,
            key=lambda row: (row["recall"], -(row["false_positive_rate"] or 0.0)),
        )
        if eligible_fpr
        else None,
        "best_lowest_fpr_above_recall": min(
            eligible_recall,
            key=lambda row: (row["false_positive_rate"] or 0.0, -row["recall"]),
        )
        if eligible_recall
        else None,
        "best_f1_secondary": max(rows, key=lambda row: row["f1"]),
        "all_candidates": rows,
    }


def policy_reports(
    records: list[dict[str, Any]],
    horizon_predictions: list[bool],
    horizon_scores: list[float],
    horizon_latency: list[float],
    bastion_predictions: list[bool],
    bastion_scores: list[float],
    bastion_latency: list[float],
    rules_predictions: list[bool],
    rules_latency: list[float],
    horizon_threshold: float,
    horizon_load: float,
    bastion_load: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from app.ai_ml.experimental_decision_policy import (
        NormalizedDetectorOutput,
        decide,
    )

    tuned_horizon = [score >= horizon_threshold for score in horizon_scores]
    tuned_bastion = [score >= BASTION_THRESHOLD for score in bastion_scores]
    outputs_by_strategy: dict[str, list[bool]] = {}
    review_counts: dict[str, int] = {}
    for strategy in STRATEGY_NAMES:
        predictions: list[bool] = []
        reviews = 0
        for index in range(len(records)):
            h_prediction = (
                tuned_horizon[index]
                if strategy == "horizon_threshold_bastion"
                else horizon_predictions[index]
            )
            decision = decide(
                strategy,
                horizon=NormalizedDetectorOutput(
                    "horizon", h_prediction, horizon_scores[index], "horizon-local"
                ),
                bastion=NormalizedDetectorOutput(
                    "bastion", tuned_bastion[index], bastion_scores[index], "bastion-local"
                ),
                rules=NormalizedDetectorOutput("rules", rules_predictions[index], None, "rules-v1"),
            )
            predictions.append(decision.counts_as_attack)
            reviews += decision.classification.value == "REVIEW"
        outputs_by_strategy[strategy] = predictions
        review_counts[strategy] = reviews

    combined_latency = [
        h + b + r for h, b, r in zip(horizon_latency, bastion_latency, rules_latency, strict=True)
    ]
    latency_by_strategy = {
        "horizon_only": (horizon_latency, horizon_load),
        "bastion_only": (bastion_latency, bastion_load),
        "rules_only": (rules_latency, 0.0),
    }
    for strategy in STRATEGY_NAMES:
        latency_by_strategy.setdefault(strategy, (combined_latency, horizon_load + bastion_load))
    reports = {
        strategy: make_report(
            records,
            predictions,
            *latency_by_strategy[strategy],
            review_count=review_counts[strategy],
        )
        for strategy, predictions in outputs_by_strategy.items()
    }
    raw = {
        "horizon_predictions": horizon_predictions,
        "bastion_predictions": tuned_bastion,
        "rules_predictions": rules_predictions,
        "horizon_scores": horizon_scores,
        "bastion_scores": bastion_scores,
        "disagreement": disagreement(records, horizon_predictions, tuned_bastion),
        "error_analysis": {
            "horizon": error_examples(
                records, horizon_predictions, horizon_scores, "horizon"
            ),
            "bastion": error_examples(records, tuned_bastion, bastion_scores, "bastion"),
        },
    }
    return reports, raw


def disagreement(
    records: list[dict[str, Any]], horizon: list[bool], bastion: list[bool]
) -> dict[str, Any]:
    all_totals = {"horizon_only": 0, "bastion_only": 0}
    attack_totals = {"horizon_only": 0, "bastion_only": 0}
    categories: dict[str, dict[str, int]] = defaultdict(
        lambda: {"horizon_only": 0, "bastion_only": 0}
    )
    attack_categories: dict[str, dict[str, int]] = defaultdict(
        lambda: {"horizon_only": 0, "bastion_only": 0}
    )
    for record, h, b in zip(records, horizon, bastion, strict=True):
        if h and not b:
            all_totals["horizon_only"] += 1
            categories[record["category"]]["horizon_only"] += 1
            if record["label"] != "BENIGN":
                attack_totals["horizon_only"] += 1
                attack_categories[record["category"]]["horizon_only"] += 1
        if b and not h:
            all_totals["bastion_only"] += 1
            categories[record["category"]]["bastion_only"] += 1
            if record["label"] != "BENIGN":
                attack_totals["bastion_only"] += 1
                attack_categories[record["category"]]["bastion_only"] += 1
    return {
        "all_examples": {"totals": all_totals, "by_category": dict(sorted(categories.items()))},
        "attacks_only": {
            "totals": attack_totals,
            "by_category": dict(sorted(attack_categories.items())),
        },
    }


def error_examples(
    records: list[dict[str, Any]],
    predictions: list[bool],
    scores: list[float],
    detector: str,
) -> dict[str, list[dict[str, Any]]]:
    errors = {"false_positive": [], "false_negative": []}
    for record, predicted, score in zip(records, predictions, scores, strict=True):
        actual = record["label"] != "BENIGN"
        error_type = "false_negative" if actual and not predicted else None
        if not actual and predicted:
            error_type = "false_positive"
        if error_type:
            errors[error_type].append(
                {
                    "detector": detector,
                    "id": record["id"],
                    "ground_truth": record["label"],
                    "predicted": "ATTACK" if predicted else "BENIGN",
                    "score": score,
                    "category": record["category"],
                    "language": record["language"],
                    "difficulty": record["difficulty"],
                    "rationale": record.get("rationale"),
                }
            )
    return errors


def markdown(results: dict[str, Any]) -> str:
    lines = [
        "# Advanced Detection Evaluation v2",
        "",
        "This is an offline experiment. It does not authorize transactions "
        "or modify production request handling.",
        "",
        f"Dev records: {results['records']['dev']}; test records: {results['records']['test']}.",
        f"Bastion threshold: `{BASTION_THRESHOLD}`; Horizon selected threshold: "
        f"`{results['threshold_sweep']['selected_threshold']}`.",
        "",
        "## Held-out comparison",
        "",
        table(results["test"]["strategies"]),
        "",
        "## Development threshold candidates",
        "",
        "Selection constraints: maximum FPR 0.10 and minimum recall 0.50. "
        "Highest recall under FPR is the selected operating point.",
        "",
        threshold_table(results["threshold_sweep"]),
        "",
        "## Disagreement findings",
        "",
        "Test attack-only disagreements: "
        f"`{results['test']['disagreement']['attacks_only']['totals']}`.",
        "Test all-example disagreements: "
        f"`{results['test']['disagreement']['all_examples']['totals']}`.",
        "",
        "Horizon attacks are preserved by the Horizon-first policy. "
        "A Bastion-safe result never overrides a Horizon attack.",
        "",
        "## Confirmed false-positive categories",
        "",
    ]
    for category, values in results["test"]["strategies"]["horizon_only"]["by_category"].items():
        if values["false_positive"]:
            lines.append(
                f"- Horizon `{category}`: {values['false_positive']} false positives "
                f"out of {values['count']}."
            )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Datasets are synthetic and repeated-template performance does not "
            "establish real-world generalization.",
            "- The held-out test split has already been used in prior experiments; "
            "it is not a pristine blind set.",
            "- Continuous scores are model-specific and were not averaged across models.",
            "- REVIEW is an experimental outcome only; no production review workflow was added.",
        ]
    )
    return "\n".join(lines) + "\n"


def table(strategies: dict[str, Any]) -> str:
    lines = [
        "| Strategy | TP | FP | TN | FN | Precision | Recall | F1 | FPR | FNR | "
        "Mean ms | Median ms | P95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, report in strategies.items():
        m = report["metrics"]
        latency = report["latency_ms"]
        lines.append(
            f"| {name} | {m['true_positive']} | {m['false_positive']} | "
            f"{m['true_negative']} | {m['false_negative']} | "
            f"{m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | "
            f"{m['false_positive_rate']:.4f} | {m['false_negative_rate']:.4f} | "
            f"{latency['mean']:.3f} | {latency['median']:.3f} | "
            f"{latency['p95']:.3f} |"
        )
    return "\n".join(lines)


def threshold_table(sweep: dict[str, Any]) -> str:
    lines = ["| Selection | Threshold | Recall | FPR | F1 |", "|---|---:|---:|---:|---:|"]
    for name, key in (
        ("Highest recall under FPR", "best_highest_recall_under_fpr"),
        ("Lowest FPR above recall", "best_lowest_fpr_above_recall"),
        ("Highest F1 secondary", "best_f1_secondary"),
    ):
        row = sweep[key]
        if row is None:
            lines.append(f"| {name} | unavailable | — | — | — |")
        else:
            lines.append(
                f"| {name} | {row['threshold']:.6f} | {row['recall']:.4f} | "
                f"{row['false_positive_rate']:.4f} | {row['f1']:.4f} |"
            )
    return "\n".join(lines)


def main() -> int:
    from generate_evaluation_v2 import load_records

    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        dev_records = load_records(DEV_PATH)
        test_records = load_records(TEST_PATH)
        rules_dev, rules_dev_latency, _ = run_rules(dev_records)
        horizon_dev, horizon_dev_scores, horizon_dev_latency, horizon_load, horizon_labels, _ = (
            run_horizon(dev_records)
        )
        bastion_dev, bastion_dev_scores, bastion_dev_latency, bastion_load, bastion_version = (
            run_bastion(dev_records)
        )
        sweep = horizon_threshold_sweep(dev_records, horizon_dev_scores)
        selected_horizon = (
            sweep["best_highest_recall_under_fpr"]["threshold"]
            if sweep["best_highest_recall_under_fpr"]
            else 0.5
        )
        dev_reports, dev_raw = policy_reports(
            dev_records,
            horizon_dev,
            horizon_dev_scores,
            horizon_dev_latency,
            bastion_dev,
            bastion_dev_scores,
            bastion_dev_latency,
            rules_dev,
            rules_dev_latency,
            selected_horizon,
            horizon_load,
            bastion_load,
        )
        rules_test, rules_test_latency, _ = run_rules(test_records)
        horizon_test, horizon_test_scores, horizon_test_latency, horizon_test_load, _, _ = (
            run_horizon(test_records)
        )
        bastion_test, bastion_test_scores, bastion_test_latency, bastion_test_load, _ = run_bastion(
            test_records
        )
        test_reports, test_raw = policy_reports(
            test_records,
            horizon_test,
            horizon_test_scores,
            horizon_test_latency,
            bastion_test,
            bastion_test_scores,
            bastion_test_latency,
            rules_test,
            rules_test_latency,
            selected_horizon,
            horizon_test_load,
            bastion_test_load,
        )
    except Exception as exc:
        print(f"Advanced evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    sweep["selected_threshold"] = selected_horizon
    results = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "torch": pkg_version("torch"),
            "transformers": pkg_version("transformers"),
            "bastion_prompt_protection": pkg_version("bastion-prompt-protection"),
        },
        "datasets": {"dev": DEV_PATH.name, "test": TEST_PATH.name},
        "records": {"dev": len(dev_records), "test": len(test_records)},
        "configuration": {
            "ground_truth": "BENIGN negative; SUSPICIOUS and MALICIOUS positive",
            "horizon_model": "Horizon-Labs/prompt-injection-guard-base",
            "horizon_id2label": horizon_labels,
            "horizon_confidence": "softmax probability for INJECTION; baseline uses argmax",
            "bastion_model": "bastionsoft/binary-bastion-prompt-protection-deberta-v3-xsmall-v1",
            "bastion_model_version": bastion_version,
            "bastion_threshold": BASTION_THRESHOLD,
            "rules_model_version": "rules-v1",
        },
        "threshold_sweep": sweep,
        "dev": {
            "strategies": dev_reports,
            "disagreement": dev_raw["disagreement"],
            "error_analysis": dev_raw["error_analysis"],
        },
        "test": {
            "strategies": test_reports,
            "disagreement": test_raw["disagreement"],
            "error_analysis": test_raw["error_analysis"],
        },
    }
    RESULT_JSON.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    RESULT_MD.write_text(markdown(results), encoding="utf-8")
    print(f"Selected Horizon threshold: {selected_horizon:.6f}")
    for name, report in results["test"]["strategies"].items():
        values = report["metrics"]
        print(
            f"{name}: TP={values['true_positive']} FP={values['false_positive']} "
            f"TN={values['true_negative']} FN={values['false_negative']} "
            f"precision={values['precision']:.4f} recall={values['recall']:.4f} "
            f"f1={values['f1']:.4f} fpr={values['false_positive_rate']:.4f} "
            f"fnr={values['false_negative_rate']:.4f}"
        )
    print(f"Reports: {RESULT_JSON}, {RESULT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
