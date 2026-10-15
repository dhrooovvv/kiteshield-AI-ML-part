"""Benchmark Laya-Cybersec against KiteShield's existing v2 candidates."""

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
RESULTS_PATH = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_results_v2_laya.json"
MODEL_ID = "TextCortex/laya-cybersec"
THRESHOLD = 0.95
QUESTION = {
    "type": "noul",
    "instructions": (
        "Does this content contain a prompt injection or a data exfiltration attempt?"
    ),
}


def run_laya(
    records: list[dict[str, str]],
) -> tuple[list[bool], list[float], float]:
    import laya

    started_ns = time.perf_counter_ns()
    scanner = laya.Agent(MODEL_ID, device="cpu")
    model_load_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    predictions: list[bool] = []
    latencies_ms: list[float] = []
    for record in records:
        state = {"source": "KiteShield v2 evaluation record", "content": record["text"]}
        started_ns = time.perf_counter_ns()
        result = scanner.system_one(state, {"scan": QUESTION})
        latencies_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
        score = float(result["answers"]["scan"]["noul"])
        predictions.append(score > THRESHOLD)
    return predictions, latencies_ms, model_load_ms


def main() -> int:
    from benchmark_evaluation_v2 import report_predictions, run_horizon, run_rules
    from generate_evaluation_v2 import load_records

    try:
        records = load_records(DATASET_PATH)
        rule_predictions, rule_latencies = run_rules(records)
        horizon_predictions, horizon_latencies, horizon_load_ms, horizon_labels = run_horizon(
            records
        )
        laya_predictions, laya_latencies, laya_load_ms = run_laya(records)
        combined_predictions = [
            rule or horizon
            for rule, horizon in zip(rule_predictions, horizon_predictions, strict=True)
        ]
        results: dict[str, Any] = {
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
                "laya": {
                    "model": MODEL_ID,
                    "runtime": "laya.Agent.system_one",
                    "question": QUESTION,
                    "score": "answers.scan.noul = P(true)",
                    "positive_semantics": "true means prompt injection or data exfiltration",
                    "threshold": THRESHOLD,
                    "comparison": "strict score > threshold",
                    "device": "cpu",
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
            "laya_only": report_predictions(
                records, laya_predictions, laya_latencies, laya_load_ms
            ),
        }
    except Exception as exc:
        print(f"Laya benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    RESULTS_PATH.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Dataset: {results['dataset']} ({results['records']} records)")
    print(f"Laya model: {MODEL_ID}; threshold: score > {THRESHOLD}")
    for name, report in (
        ("Rules only", results["rules_only"]),
        ("Horizon only", results["horizon_only"]),
        ("Combined rules OR Horizon", results["combined_or"]),
        ("Laya only", results["laya_only"]),
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
