"""Benchmark Meta Prompt Guard alongside KiteShield's existing candidates."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
for path in (PROJECT_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DATASET_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_test_v2.jsonl"
RESULTS_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_results_v2_prompt_guard.json"
MODEL_ID = "meta-llama/Prompt-Guard-86M"


def load_prompt_guard() -> tuple[Any, Any, dict[int, str], Any, float]:
    """Load Prompt Guard from the local cache only and return its config mapping."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    started_ns = time.perf_counter_ns()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_ID,
        local_files_only=True,
    )
    model.eval()
    device = torch.device("cpu")
    model.to(device)
    load_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    id2label = {int(key): value.upper() for key, value in model.config.id2label.items()}
    required = {"BENIGN", "INJECTION", "JAILBREAK"}
    if set(id2label.values()) != required:
        raise RuntimeError(f"Unexpected Prompt Guard labels: {id2label}")
    return tokenizer, model, id2label, device, load_ms


def run_prompt_guard(
    records: list[dict[str, str]],
) -> tuple[list[bool], list[float], dict[int, str], float]:
    import torch

    tokenizer, model, id2label, device, load_ms = load_prompt_guard()
    positive_ids = {key for key, value in id2label.items() if value in {"INJECTION", "JAILBREAK"}}
    predictions: list[bool] = []
    latencies_ms: list[float] = []
    with torch.inference_mode():
        for record in records:
            started_ns = time.perf_counter_ns()
            inputs = tokenizer(
                record["text"],
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            )
            inputs = {name: value.to(device) for name, value in inputs.items()}
            logits = model(**inputs).logits
            predicted_id = int(torch.argmax(logits, dim=-1).item())
            latencies_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
            predictions.append(predicted_id in positive_ids)
    return predictions, latencies_ms, id2label, load_ms


def main() -> int:
    from benchmark_evaluation_v2 import report_predictions, run_horizon, run_rules
    from generate_evaluation_v2 import load_records

    try:
        records = load_records(DATASET_PATH)
        rule_predictions, rule_latencies = run_rules(records)
        (
            horizon_predictions,
            horizon_latencies,
            horizon_load_ms,
            horizon_labels,
        ) = run_horizon(records)
        (
            prompt_predictions,
            prompt_latencies,
            prompt_labels,
            prompt_load_ms,
        ) = run_prompt_guard(records)
        combined_predictions = [
            rule or horizon
            for rule, horizon in zip(rule_predictions, horizon_predictions, strict=True)
        ]
        results = {
            "dataset": DATASET_PATH.name,
            "records": len(records),
            "configuration": {
                "rules": "InjectionScreen rules-v1, unchanged",
                "horizon": {
                    "model": "Horizon-Labs/prompt-injection-guard-base",
                    "id2label": horizon_labels,
                    "decision": "argmax(logits)",
                    "explicit_threshold": None,
                },
                "prompt_guard": {
                    "model": MODEL_ID,
                    "id2label": prompt_labels,
                    "positive_labels": ["INJECTION", "JAILBREAK"],
                    "decision": "argmax(logits)",
                    "explicit_threshold": None,
                    "max_length": 512,
                    "local_files_only": True,
                },
                "combined": "existing rules OR Horizon policy",
            },
            "rules_only": report_predictions(records, rule_predictions, rule_latencies),
            "horizon_only": report_predictions(
                records, horizon_predictions, horizon_latencies, horizon_load_ms
            ),
            "combined_or": report_predictions(
                records,
                combined_predictions,
                [
                    rule + horizon
                    for rule, horizon in zip(rule_latencies, horizon_latencies, strict=True)
                ],
                horizon_load_ms,
            ),
            "prompt_guard_only": report_predictions(
                records, prompt_predictions, prompt_latencies, prompt_load_ms
            ),
        }
    except Exception as exc:
        print(f"Prompt Guard benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    RESULTS_PATH.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Dataset: {results['dataset']} ({results['records']} records)")
    print(f"Prompt Guard labels: {prompt_labels}; positive={['INJECTION', 'JAILBREAK']}")
    print("Decision rule: argmax(logits); explicit threshold: not configured")
    print("Prompt Guard preprocessing: padding=True, truncation=True, max_length=512")
    for name, report in (
        ("Rules only", results["rules_only"]),
        ("Horizon only", results["horizon_only"]),
        ("Combined rules OR Horizon", results["combined_or"]),
        ("Prompt Guard only", results["prompt_guard_only"]),
    ):
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
    print(f"Results: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
