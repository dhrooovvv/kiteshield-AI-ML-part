"""Single-run offline benchmark for the frozen final v3 dataset."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from benchmark_advanced_detection_v2 import (  # noqa: E402
    policy_reports,
    run_bastion,
    run_horizon,
    run_rules,
    table,
)
from generate_evaluation_v2 import load_records  # noqa: E402

DATASET = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_final_v3.jsonl"
REPORT_DIR = PROJECT_ROOT / "reports"
RESULT_JSON = REPORT_DIR / "evaluation_final_v3_results.json"
RESULT_MD = REPORT_DIR / "evaluation_final_v3_results.md"
HORIZON_THRESHOLD = 0.9352320432662964
BASTION_THRESHOLD = 0.059


def main() -> int:
    before_hash = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    records = load_records(DATASET)
    try:
        rules, rules_latency, _ = run_rules(records)
        horizon, horizon_scores, horizon_latency, horizon_load, horizon_labels, _ = run_horizon(
            records
        )
        bastion, bastion_scores, bastion_latency, bastion_load, bastion_version = run_bastion(
            records
        )
        reports, raw = policy_reports(
            records,
            horizon,
            horizon_scores,
            horizon_latency,
            bastion,
            bastion_scores,
            bastion_latency,
            rules,
            rules_latency,
            HORIZON_THRESHOLD,
            horizon_load,
            bastion_load,
        )
    except Exception as exc:
        print(f"Final v3 benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    after_hash = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    if before_hash != after_hash:
        print(
            "Final v3 dataset changed during benchmark; refusing to write results.", file=sys.stderr
        )
        return 1
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    results = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "dataset": {
            "path": str(DATASET),
            "filename": DATASET.name,
            "sha256": after_hash,
            "records": len(records),
        },
        "configuration": {
            "ground_truth": "BENIGN negative; SUSPICIOUS and MALICIOUS positive",
            "horizon_threshold": HORIZON_THRESHOLD,
            "bastion_threshold": BASTION_THRESHOLD,
            "horizon_labels": horizon_labels,
            "bastion_model_version": bastion_version,
            "rules_model_version": "rules-v1",
            "threshold_source": "previously selected on v2 development data; no v3 tuning",
        },
        "strategies": reports,
        "disagreement": raw["disagreement"],
        "error_analysis": raw["error_analysis"],
    }
    RESULT_JSON.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Final v3 Prompt-Injection Evaluation",
        "",
        "This is a single-run offline benchmark. It does not authorize transactions "
        "or modify production request handling.",
        "",
        f"Dataset: `{DATASET.name}`; records: `{len(records)}`; SHA-256: `{after_hash}`.",
        f"Frozen thresholds: Horizon `{HORIZON_THRESHOLD}`; Bastion `{BASTION_THRESHOLD}`.",
        "",
        "## Comparison",
        "",
        table(reports),
        "",
        "Model-loading time and per-example mean/median/P95 latency are included "
        "in the JSON result for each strategy.",
        "The selected experimental strategy is `horizon_threshold_bastion`; model "
        "disagreement is not treated as proof of safety.",
        "",
        "## Limitations",
        "",
        "This synthetic dataset measures synthetic performance only and does not "
        "establish real-world generalization.",
        "The dataset is intentionally independent from the audited v1/v2 text "
        "corpus, but its coverage remains limited.",
    ]
    RESULT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    selected = reports["horizon_threshold_bastion"]
    metrics = selected["metrics"]
    print(
        json.dumps(
            {
                "dataset_sha256": after_hash,
                "strategy": "horizon_threshold_bastion",
                "metrics": metrics,
                "latency_ms": selected["latency_ms"],
                "reports": [str(RESULT_JSON), str(RESULT_MD)],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
