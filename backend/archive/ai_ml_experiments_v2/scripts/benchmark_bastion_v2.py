"""Benchmark Bastion Prompt Protection on KiteShield's unchanged v2 splits."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
for path in (PROJECT_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DEV_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_dev_v2.jsonl"
TEST_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_test_v2.jsonl"
RESULTS_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_results_v2_bastion.json"
BASTION_DEFAULT_THRESHOLD = 0.50
MIN_DEV_RECALL = 0.50
MAX_DEV_FPR = 0.10


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
    grouped: dict[str, tuple[list[dict[str, Any]], list[bool]]] = {}
    for record, prediction in zip(records, predictions, strict=True):
        key = str(record[field])
        if key not in grouped:
            grouped[key] = ([], [])
        grouped[key][0].append(record)
        grouped[key][1].append(prediction)
    return {key: metrics(counts(*value)) for key, value in sorted(grouped.items())}


def latency_report(latencies_ms: list[float], model_load_ms: float) -> dict[str, float]:
    ordered = sorted(latencies_ms)
    index = max(0, min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1))
    return {
        "mean": sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0,
        "median": statistics.median(latencies_ms) if latencies_ms else 0.0,
        "p95": ordered[index] if ordered else 0.0,
        "model_load": model_load_ms,
    }


def report(
    records: list[dict[str, Any]],
    predictions: list[bool],
    latencies_ms: list[float],
    model_load_ms: float = 0.0,
) -> dict[str, Any]:
    return {
        "metrics": metrics(counts(records, predictions)),
        "by_category": grouped_metrics(records, predictions, "category"),
        "by_language": grouped_metrics(records, predictions, "language"),
        "by_difficulty": grouped_metrics(records, predictions, "difficulty"),
        "latency_ms": latency_report(latencies_ms, model_load_ms),
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
            inputs = tokenizer(record["text"], return_tensors="pt", truncation=True, max_length=512)
            inputs = {name: value.to(device) for name, value in inputs.items()}
            logits = model(**inputs).logits
            latencies_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
            predictions.append(int(torch.argmax(logits, dim=-1).item()) == injection_id)
    return predictions, latencies_ms, model_load_ms, id2label


def run_bastion(
    records_by_split: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    from bastion_prompt_protection import Guard, Preset

    guard = Guard(preset=Preset.TINY)
    if guard.config.thresholds.attack_above != BASTION_DEFAULT_THRESHOLD:
        raise RuntimeError("Unexpected Bastion default attack threshold")
    binary_stage = guard._binary
    if binary_stage is None:
        raise RuntimeError("Bastion binary stage is disabled")
    load_started_ns = time.perf_counter_ns()
    if not binary_stage._loader.is_available():
        raise RuntimeError("Bastion binary model is unavailable")
    model_load_ms = (time.perf_counter_ns() - load_started_ns) / 1_000_000

    raw: dict[str, dict[str, Any]] = {}
    all_scores: dict[str, list[float]] = {}
    for split, records in records_by_split.items():
        scores: list[float] = []
        latencies_ms: list[float] = []
        for record in records:
            started_ns = time.perf_counter_ns()
            result = guard.protect(record["text"])
            latencies_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
            if result.label not in {"safe", "attack"}:
                raise RuntimeError(f"Unexpected Bastion label: {result.label}")
            if not 0.0 <= result.risk <= 1.0:
                raise RuntimeError(f"Unexpected Bastion risk: {result.risk}")
            scores.append(float(result.risk))
        all_scores[split] = scores
        raw[split] = {
            "scores": scores,
            "latencies_ms": latencies_ms,
            "model_version": guard.model_version,
        }

    dev_records = records_by_split["dev"]
    dev_scores = all_scores["dev"]
    candidates = sorted({BASTION_DEFAULT_THRESHOLD, *dev_scores})
    eligible: list[tuple[float, dict[str, Any]]] = []
    for threshold in candidates:
        predictions = [score >= threshold for score in dev_scores]
        current = metrics(counts(dev_records, predictions))
        if (
            current["recall"] >= MIN_DEV_RECALL
            and current["false_positive_rate"] is not None
            and current["false_positive_rate"] <= MAX_DEV_FPR
        ):
            eligible.append((threshold, current))
    if not eligible:
        raise RuntimeError("No development threshold met the minimum recall constraint")
    selected_threshold, selected_metrics = max(
        eligible,
        key=lambda item: (
            item[1]["f1"],
            -(item[1]["false_positive_rate"] or 0.0),
            item[1]["recall"],
            item[0],
        ),
    )

    reports: dict[str, dict[str, Any]] = {}
    for split, records in records_by_split.items():
        scores = all_scores[split]
        raw_data = raw[split]
        default_predictions = [score >= BASTION_DEFAULT_THRESHOLD for score in scores]
        tuned_predictions = [score >= selected_threshold for score in scores]
        reports[split] = {
            "default": report(
                records,
                default_predictions,
                raw_data["latencies_ms"],
                model_load_ms,
            ),
            "tuned": report(
                records,
                tuned_predictions,
                raw_data["latencies_ms"],
                model_load_ms,
            ),
        }
    tuning = {
        "selected_threshold": selected_threshold,
        "minimum_dev_recall": MIN_DEV_RECALL,
        "maximum_dev_fpr": MAX_DEV_FPR,
        "selection_rule": (
            "max dev F1 subject to recall >= minimum and FPR <= maximum; "
            "tie-break lower FPR, higher recall, higher threshold"
        ),
        "selected_dev_metrics": selected_metrics,
        "default_threshold": BASTION_DEFAULT_THRESHOLD,
        "model_version": raw["test"]["model_version"],
        "label_mapping": {"safe": False, "attack": True},
        "risk_semantics": (
            "GuardResult.risk in [0,1]; package label uses risk >= "
            "thresholds.attack_above"
        ),
    }
    return reports, tuning


def main() -> int:
    from generate_evaluation_v2 import load_records

    try:
        records_by_split = {
            "dev": load_records(DEV_PATH),
            "test": load_records(TEST_PATH),
        }
        bastion_reports, tuning = run_bastion(records_by_split)
        rules_reports: dict[str, Any] = {}
        horizon_reports: dict[str, Any] = {}
        model_configs: dict[str, Any] = {}
        for split, records in records_by_split.items():
            rule_predictions, rule_latencies = run_rules(records)
            rules_reports[split] = report(records, rule_predictions, rule_latencies)
            horizon_predictions, horizon_latencies, load_ms, id2label = run_horizon(records)
            horizon_reports[split] = report(
                records, horizon_predictions, horizon_latencies, load_ms
            )
            model_configs[split] = {"horizon_id2label": id2label}
    except Exception as exc:
        print(f"Bastion benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    results = {
        "datasets": {split: path.name for split, path in (("dev", DEV_PATH), ("test", TEST_PATH))},
        "records": {split: len(records) for split, records in records_by_split.items()},
        "configuration": {
            "rules": "InjectionScreen rules-v1, unchanged; label != BENIGN is positive",
            "horizon": {
                "model": "Horizon-Labs/prompt-injection-guard-base",
                "decision": "argmax(logits), INJECTION is positive",
                "split_configs": model_configs,
            },
            "bastion": {
                "package": "bastion-prompt-protection",
                "preset": "tiny",
                "model": "bastionsoft/binary-bastion-prompt-protection-deberta-v3-xsmall-v1",
                "runtime": "Guard.protect",
                "device": "CPUExecutionProvider",
            },
        },
        "threshold_tuning": tuning,
        "rules_only": rules_reports,
        "horizon_only": horizon_reports,
        "bastion_only": bastion_reports,
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Dev records: {results['records']['dev']}; test records: {results['records']['test']}")
    print(f"Bastion selected dev threshold: {tuning['selected_threshold']:.6f}")
    for split in ("dev", "test"):
        print(split)
        for name, result in (
            ("Rules only", rules_reports[split]),
            ("Horizon only", horizon_reports[split]),
            ("Bastion default", bastion_reports[split]["default"]),
            ("Bastion tuned", bastion_reports[split]["tuned"]),
        ):
            values = result["metrics"]
            latency = result["latency_ms"]
            print(
                f"  {name}: precision={values['precision']:.4f} recall={values['recall']:.4f} "
                f"f1={values['f1']:.4f} fpr={values['false_positive_rate']:.4f} "
                f"fnr={values['false_negative_rate']:.4f} "
                f"latency_mean={latency['mean']:.3f} median={latency['median']:.3f} "
                f"p95={latency['p95']:.3f} load={latency['model_load']:.3f}"
            )
    print(f"Results: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
