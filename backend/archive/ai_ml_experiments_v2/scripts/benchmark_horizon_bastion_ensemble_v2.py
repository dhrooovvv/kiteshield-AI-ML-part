"""Evaluate experimental Horizon/Bastion/rules ensemble strategies."""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
for path in (PROJECT_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DEV_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_dev_v2.jsonl"
TEST_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_test_v2.jsonl"
RESULTS_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_results_v2_ensemble.json"
BASTION_THRESHOLD_DEFAULT = 0.50
MIN_DEV_RECALL = 0.50
MAX_DEV_FPR = 0.10


def metric_counts(records: list[dict[str, Any]], predictions: list[bool]) -> dict[str, int]:
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


def metrics(values: dict[str, int]) -> dict[str, float | int | None]:
    tp = values["true_positive"]
    fp = values["false_positive"]
    tn = values["true_negative"]
    fn = values["false_negative"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        **values,
        "count": tp + fp + tn + fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negative_rate": fn / (fn + tp) if fn + tp else None,
    }


def grouped_metrics(
    records: list[dict[str, Any]], predictions: list[bool], field: str
) -> dict[str, Any]:
    groups: dict[str, tuple[list[dict[str, Any]], list[bool]]] = {}
    for record, predicted in zip(records, predictions, strict=True):
        key = str(record[field])
        if key not in groups:
            groups[key] = ([], [])
        groups[key][0].append(record)
        groups[key][1].append(predicted)
    return {key: metrics(metric_counts(*value)) for key, value in sorted(groups.items())}


def percentile(values: list[float], percentage: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentage * len(ordered)) - 1))
    return ordered[index]


def report(
    records: list[dict[str, Any]],
    predictions: list[bool],
    latencies_ms: list[float],
    model_load_ms: float,
) -> dict[str, Any]:
    return {
        "metrics": metrics(metric_counts(records, predictions)),
        "by_category": grouped_metrics(records, predictions, "category"),
        "by_language": grouped_metrics(records, predictions, "language"),
        "by_difficulty": grouped_metrics(records, predictions, "difficulty"),
        "latency_ms": {
            "mean": statistics.mean(latencies_ms) if latencies_ms else 0.0,
            "median": statistics.median(latencies_ms) if latencies_ms else 0.0,
            "p95": percentile(latencies_ms, 0.95),
            "model_load": model_load_ms,
        },
    }


def run_rules(records: list[dict[str, Any]]) -> tuple[list[bool], list[float]]:
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
    records: list[dict[str, Any]],
) -> tuple[list[bool], list[float], list[float], float, dict[int, str]]:
    import torch
    from benchmark_horizon_guard import load_classifier

    started_ns = time.perf_counter_ns()
    tokenizer, model, id2label, device = load_classifier()
    load_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    injection_id = next(key for key, value in id2label.items() if value == "INJECTION")
    predictions: list[bool] = []
    scores: list[float] = []
    latencies_ms: list[float] = []
    with torch.inference_mode():
        for record in records:
            inputs = tokenizer(record["text"], return_tensors="pt", truncation=True, max_length=512)
            inputs = {name: value.to(device) for name, value in inputs.items()}
            started_ns = time.perf_counter_ns()
            logits = model(**inputs).logits
            latencies_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
            probabilities = torch.softmax(logits, dim=-1)[0]
            predicted_id = int(torch.argmax(probabilities).item())
            predictions.append(predicted_id == injection_id)
            scores.append(float(probabilities[injection_id].item()))
    return predictions, scores, latencies_ms, load_ms, id2label


def run_bastion(
    records: list[dict[str, Any]],
) -> tuple[list[bool], list[float], list[float], float, str | None]:
    from bastion_prompt_protection import Guard, Preset

    guard = Guard(preset=Preset.TINY)
    if guard.config.thresholds.attack_above != BASTION_THRESHOLD_DEFAULT:
        raise RuntimeError("Unexpected Bastion default threshold")
    if guard._binary is None:
        raise RuntimeError("Bastion binary stage is disabled")
    started_ns = time.perf_counter_ns()
    if not guard._binary._loader.is_available():
        raise RuntimeError("Bastion binary model is unavailable")
    load_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    predictions: list[bool] = []
    scores: list[float] = []
    latencies_ms: list[float] = []
    for record in records:
        started_ns = time.perf_counter_ns()
        result = guard.protect(record["text"])
        latencies_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
        if result.label not in {"safe", "attack"} or not 0.0 <= result.risk <= 1.0:
            raise RuntimeError(f"Unexpected Bastion result: {result.to_dict()}")
        predictions.append(result.label == "attack")
        scores.append(float(result.risk))
    return predictions, scores, latencies_ms, load_ms, guard.model_version


def select_bastion_threshold(records: list[dict[str, Any]], scores: list[float]) -> dict[str, Any]:
    candidates = sorted({BASTION_THRESHOLD_DEFAULT, *scores})
    eligible: list[tuple[float, dict[str, Any]]] = []
    for threshold in candidates:
        predictions = [score >= threshold for score in scores]
        current = metrics(metric_counts(records, predictions))
        if (
            current["recall"] >= MIN_DEV_RECALL
            and current["false_positive_rate"] is not None
            and current["false_positive_rate"] <= MAX_DEV_FPR
        ):
            eligible.append((threshold, current))
    if not eligible:
        raise RuntimeError("No Bastion development threshold met the selection constraints")
    threshold, selected_metrics = max(
        eligible,
        key=lambda item: (
            item[1]["f1"],
            -(item[1]["false_positive_rate"] or 0.0),
            item[1]["recall"],
            item[0],
        ),
    )
    return {
        "selected_threshold": threshold,
        "default_threshold": BASTION_THRESHOLD_DEFAULT,
        "minimum_dev_recall": MIN_DEV_RECALL,
        "maximum_dev_fpr": MAX_DEV_FPR,
        "selection_rule": "max dev F1 subject to recall >= minimum and FPR <= maximum",
        "selected_dev_metrics": selected_metrics,
    }


def disagreement_report(
    records: list[dict[str, Any]],
    horizon: list[bool],
    bastion: list[bool],
) -> dict[str, Any]:
    categories: dict[str, dict[str, int]] = defaultdict(
        lambda: {"horizon_only": 0, "bastion_only": 0}
    )
    attack_categories: dict[str, dict[str, int]] = defaultdict(
        lambda: {"horizon_only": 0, "bastion_only": 0}
    )
    totals = {"horizon_only": 0, "bastion_only": 0}
    attack_totals = {"horizon_only": 0, "bastion_only": 0}
    for record, h, b in zip(records, horizon, bastion, strict=True):
        actual_attack = record["label"] != "BENIGN"
        if h and not b:
            totals["horizon_only"] += 1
            categories[record["category"]]["horizon_only"] += 1
            if actual_attack:
                attack_totals["horizon_only"] += 1
                attack_categories[record["category"]]["horizon_only"] += 1
        if b and not h:
            totals["bastion_only"] += 1
            categories[record["category"]]["bastion_only"] += 1
            if actual_attack:
                attack_totals["bastion_only"] += 1
                attack_categories[record["category"]]["bastion_only"] += 1
    return {
        "all_examples": {"totals": totals, "by_category": dict(sorted(categories.items()))},
        "attacks_only": {
            "totals": attack_totals,
            "by_category": dict(sorted(attack_categories.items())),
        },
    }


def evaluate_split(
    records: list[dict[str, Any]],
    bastion_threshold: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rules, rule_latency = run_rules(records)
    horizon, horizon_scores, horizon_latency, horizon_load, horizon_labels = run_horizon(records)
    bastion_default, bastion_scores, bastion_latency, bastion_load, bastion_version = run_bastion(
        records
    )
    bastion_tuned = [score >= bastion_threshold for score in bastion_scores]
    all_latency = [
        rule + horizon_time + bastion_time
        for rule, horizon_time, bastion_time in zip(
            rule_latency, horizon_latency, bastion_latency, strict=True
        )
    ]
    total_load = horizon_load + bastion_load
    horizon_or_bastion = [h or b for h, b in zip(horizon, bastion_tuned, strict=True)]
    horizon_and_bastion = [h and b for h, b in zip(horizon, bastion_tuned, strict=True)]
    horizon_first = [
        h or (b and rule)
        for h, b, rule in zip(horizon, bastion_tuned, rules, strict=True)
    ]
    three_layer_or = [
        rule or h or b for rule, h, b in zip(rules, horizon, bastion_tuned, strict=True)
    ]
    strategies = {
        "horizon_only": (horizon, horizon_latency, horizon_load),
        "bastion_only": (bastion_tuned, bastion_latency, bastion_load),
        "rules_only": (rules, rule_latency, 0.0),
        "horizon_or_bastion": (horizon_or_bastion, all_latency, total_load),
        "horizon_and_bastion": (horizon_and_bastion, all_latency, total_load),
        "horizon_first_risk_based": (horizon_first, all_latency, total_load),
        "three_layer_or": (three_layer_or, all_latency, total_load),
    }
    reports = {
        name: report(records, predictions, latency, load)
        for name, (predictions, latency, load) in strategies.items()
    }
    raw = {
        "horizon": horizon,
        "horizon_scores": horizon_scores,
        "bastion_default": bastion_default,
        "bastion_tuned": bastion_tuned,
        "bastion_scores": bastion_scores,
        "rules": rules,
        "horizon_labels": horizon_labels,
        "bastion_model_version": bastion_version,
        "disagreement": disagreement_report(records, horizon, bastion_tuned),
    }
    return reports, raw


def main() -> int:
    from generate_evaluation_v2 import load_records

    try:
        dev_records = load_records(DEV_PATH)
        test_records = load_records(TEST_PATH)
        _, dev_raw = evaluate_split(dev_records, BASTION_THRESHOLD_DEFAULT)
        tuning = select_bastion_threshold(dev_records, dev_raw["bastion_scores"])
        dev_reports, dev_raw = evaluate_split(dev_records, tuning["selected_threshold"])
        test_reports, test_raw = evaluate_split(test_records, tuning["selected_threshold"])
    except Exception as exc:
        print(f"Ensemble benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    results = {
        "datasets": {"dev": DEV_PATH.name, "test": TEST_PATH.name},
        "records": {"dev": len(dev_records), "test": len(test_records)},
        "threshold_tuning": tuning,
        "configuration": {
            "label_mapping": {
                "ground_truth": "BENIGN is negative; SUSPICIOUS/MALICIOUS are positive",
                "horizon": "config id2label INJECTION is positive",
                "bastion": "GuardResult.label attack is positive; risk >= threshold",
                "rules": "InjectionScreen label != BENIGN is positive",
            },
            "horizon": {
                "model": "Horizon-Labs/prompt-injection-guard-base",
                "decision": "argmax(logits)",
                "confidence": "softmax probability of INJECTION",
            },
            "bastion": {
                "package": "bastion-prompt-protection",
                "model": "bastionsoft/binary-bastion-prompt-protection-deberta-v3-xsmall-v1",
                "runtime": "Guard.protect; heuristics + binary stage",
                "confidence": "GuardResult.risk",
                "model_version": test_raw["bastion_model_version"],
            },
            "strategies": {
                "horizon_or_bastion": "Horizon attack OR tuned Bastion attack",
                "horizon_and_bastion": "Horizon attack AND tuned Bastion attack",
                "horizon_first_risk_based": (
                    "If Horizon attacks, retain attack regardless of Bastion; "
                    "if Horizon is benign, "
                    "require tuned Bastion AND rules to flag. Bastion-safe never overrides Horizon."
                ),
                "three_layer_or": "rules OR Horizon OR tuned Bastion",
            },
        },
        "dev": {"strategies": dev_reports, "disagreement": dev_raw["disagreement"]},
        "test": {"strategies": test_reports, "disagreement": test_raw["disagreement"]},
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Selected Bastion threshold from dev: {tuning['selected_threshold']:.6f}")
    for split, reports in (("dev", dev_reports), ("test", test_reports)):
        print(split)
        for name, current in reports.items():
            values = current["metrics"]
            latency = current["latency_ms"]
            print(
                f"  {name}: TP={values['true_positive']} FP={values['false_positive']} "
                f"TN={values['true_negative']} FN={values['false_negative']} "
                f"precision={values['precision']:.4f} recall={values['recall']:.4f} "
                f"f1={values['f1']:.4f} fpr={values['false_positive_rate']:.4f} "
                f"fnr={values['false_negative_rate']:.4f} "
                f"mean={latency['mean']:.3f} median={latency['median']:.3f} "
                f"p95={latency['p95']:.3f} load={latency['model_load']:.3f}"
            )
        disagreement = results[split]["disagreement"]
        print(f"  disagreements all examples: {disagreement['all_examples']['totals']}")
        print(f"  disagreements attacks only: {disagreement['attacks_only']['totals']}")
    print(f"Results: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
