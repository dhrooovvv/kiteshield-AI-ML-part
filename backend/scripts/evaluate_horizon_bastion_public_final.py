"""Evaluate Horizon and the existing Horizon+Bastion policy on a public split."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "0")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
for path in (PROJECT_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from benchmark_advanced_detection_v2 import (  # noqa: E402
    policy_reports,
    run_bastion,
    run_horizon,
    run_rules,
    table,
)
from huggingface_hub import HfApi  # noqa: E402
from huggingface_hub.utils import get_session  # noqa: E402

DATASET_ID = "neuralchemy/Prompt-injection-dataset"
CONFIG = "core"
TEST_SPLIT = "test"
VALIDATION_SPLIT = "validation"
PAGE_SIZE = 100
HORIZON_THRESHOLD = 0.9352320432662964
BASTION_THRESHOLD = 0.059
REPORT_DIR = PROJECT_ROOT / "reports"
MANIFEST_PATH = REPORT_DIR / "horizon_bastion_public_dataset_manifest.json"
RESULT_JSON = REPORT_DIR / "horizon_bastion_public_final.json"
RESULT_MD = REPORT_DIR / "horizon_bastion_public_final.md"


def fetch_rows(split: str) -> tuple[list[dict[str, Any]], int]:
    session = get_session()
    rows: list[dict[str, Any]] = []
    offset = 0
    total: int | None = None
    while total is None or offset < total:
        for attempt in range(3):
            try:
                response = session.get(
                    "https://datasets-server.huggingface.co/rows",
                    params={
                        "dataset": DATASET_ID,
                        "config": CONFIG,
                        "split": split,
                        "offset": offset,
                        "length": PAGE_SIZE,
                    },
                    timeout=60,
                )
                response.raise_for_status()
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
        payload = response.json()
        total = int(payload["num_rows_total"])
        page = [item["row"] for item in payload["rows"]]
        rows.extend(page)
        offset += len(page)
        if not page:
            break
    if total is None:
        raise RuntimeError(f"No row-count metadata returned for split {split}")
    return rows, total


def prepare_rows(
    rows: list[dict[str, Any]], split: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prepared: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen_text: dict[str, int] = {}
    for index, row in enumerate(rows):
        text = row.get("text")
        label = row.get("label")
        reason: str | None = None
        if not isinstance(text, str) or not text.strip():
            reason = "missing_or_empty_text"
        elif label not in (0, 1):
            reason = "non_binary_label"
        elif text in seen_text:
            reason = f"duplicate_text_of_row_{seen_text[text]}"
        if reason:
            exclusions.append({"split": split, "row_index": index, "reason": reason})
            continue
        seen_text[text] = index
        prepared.append(
            {
                "id": f"neuralchemy-core-{split}-{index:04d}",
                "text": text,
                "label": "MALICIOUS" if label == 1 else "BENIGN",
                "category": str(row.get("category") or "unknown"),
                "language": "English",
                "difficulty": str(row.get("severity") or "unspecified"),
                "rationale": "Imported from NeurAlchemy public dataset; "
                "original metadata preserved.",
                "source": row.get("source"),
                "severity": row.get("severity"),
                "group_id": row.get("group_id"),
                "augmented": row.get("augmented"),
                "tags": row.get("tags") or [],
            }
        )
    return prepared, exclusions


def canonical_hash(rows: list[dict[str, Any]]) -> str:
    payload = "\n".join(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    try:
        info = HfApi().dataset_info(DATASET_ID, files_metadata=True)
        test_rows, test_total = fetch_rows(TEST_SPLIT)
        validation_rows, validation_total = fetch_rows(VALIDATION_SPLIT)
        records, test_exclusions = prepare_rows(test_rows, TEST_SPLIT)
        _, validation_exclusions = prepare_rows(validation_rows, VALIDATION_SPLIT)
        if len(records) != test_total:
            raise RuntimeError(f"Expected all valid test rows, got {len(records)} of {test_total}")
        if test_exclusions:
            raise RuntimeError(f"Test split requires exclusions: {test_exclusions}")
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
        print(f"Public benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    manifest = {
        "dataset_id": DATASET_ID,
        "dataset_revision": info.sha,
        "source_url": f"https://huggingface.co/datasets/{DATASET_ID}",
        "license": "apache-2.0",
        "configuration": CONFIG,
        "requested_splits": {"test": TEST_SPLIT, "validation": VALIDATION_SPLIT},
        "reported_counts": {"test": test_total, "validation": validation_total},
        "fetched_counts": {"test": len(test_rows), "validation": len(validation_rows)},
        "prepared_test_count": len(records),
        "label_mapping": {"0": "BENIGN", "1": "MALICIOUS"},
        "kiteShield_positive_class": ["SUSPICIOUS", "MALICIOUS"],
        "test_exclusions": test_exclusions,
        "validation_exclusions": validation_exclusions,
        "test_duplicate_text_count": len(test_rows) - len({row.get("text") for row in test_rows}),
        "test_prepared_sha256": canonical_hash(records),
        "thresholds": {
            "horizon": HORIZON_THRESHOLD,
            "bastion": BASTION_THRESHOLD,
            "source": "existing v2 development-selected values; no public-test tuning",
        },
        "metadata_preserved": ["category", "source", "severity", "group_id", "augmented", "tags"],
        "exclusion_policy": "Fail rather than silently exclude a test row; "
        "no test rows were excluded.",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    result = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "dataset_manifest": MANIFEST_PATH.name,
        "dataset": manifest,
        "configuration": {
            "horizon_labels": horizon_labels,
            "bastion_model_version": bastion_version,
            "horizon_threshold": HORIZON_THRESHOLD,
            "bastion_threshold": BASTION_THRESHOLD,
            "decision_logic": "existing horizon_threshold_bastion policy: "
            "Horizon positive OR Bastion positive",
        },
        "strategies": {
            "horizon_only": reports["horizon_only"],
            "horizon_threshold_bastion": reports["horizon_threshold_bastion"],
        },
        "disagreement": raw["disagreement"],
        "error_analysis": raw["error_analysis"],
        "source_counts": {
            "test_labels": dict(Counter(row["label"] for row in records)),
            "test_categories": dict(Counter(row["category"] for row in records)),
        },
    }
    RESULT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Horizon vs Horizon + Bastion: NeurAlchemy Public Final",
        "",
        "Offline evaluation only. No production authorization, policy, capability, "
        "or signer code was changed.",
        "",
        f"Dataset: `{DATASET_ID}`; configuration: `{CONFIG}`; split: `{TEST_SPLIT}`; "
        f"rows: `{len(records)}`.",
        f"Dataset revision: `{info.sha}`; prepared-test SHA-256: "
        f"`{manifest['test_prepared_sha256']}`.",
        f"Frozen thresholds: Horizon `{HORIZON_THRESHOLD}`; Bastion `{BASTION_THRESHOLD}`.",
        "",
        "## Comparison",
        "",
        table({name: reports[name] for name in ("horizon_only", "horizon_threshold_bastion")}),
        "",
        "Model-loading time is reported separately in each strategy's "
        "`latency_ms.model_load` field.",
        "Performance is broken down by dataset category in the machine-readable result.",
        "",
        "## Representative errors",
        "",
    ]
    for detector in ("horizon", "bastion"):
        errors = raw["error_analysis"][detector]
        lines.append(f"### {detector.title()}")
        lines.append("")
        for kind in ("false_positive", "false_negative"):
            examples = errors[kind]
            lines.append(f"- {kind.replace('_', ' ').title()}: {len(examples)}")
            for item in examples[:5]:
                lines.append(
                    f"  - `{item['id']}`; category `{item['category']}`; "
                    f"score `{item['score']:.6f}`; "
                    f"difficulty `{item['difficulty']}`."
                )
        lines.append("")
    lines.extend(
        [
            "## Limitations",
            "",
            "The dataset is public and externally sourced, but benchmark results "
            "do not establish real-world fintech security.",
            "The public dataset was not designed specifically for wallet "
            "authorization and may not represent transaction-specific threats.",
        ]
    )
    RESULT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    selected = reports["horizon_threshold_bastion"]
    print(
        json.dumps(
            {
                "records": len(records),
                "manifest": str(MANIFEST_PATH),
                "results": str(RESULT_JSON),
                "selected_metrics": selected["metrics"],
                "selected_latency_ms": selected["latency_ms"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
