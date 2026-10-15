"""Audit KiteShield v2 JSONL data without modifying it."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AI_DIR = PROJECT_ROOT / "app" / "ai_ml"
REPORT_DIR = PROJECT_ROOT / "reports"
DEV_PATH = AI_DIR / "evaluation_dev_v2.jsonl"
TEST_PATH = AI_DIR / "evaluation_test_v2.jsonl"
REPORT_JSON = REPORT_DIR / "evaluation_dataset_v2_audit.json"
REPORT_MD = REPORT_DIR / "evaluation_dataset_v2_audit.md"
REQUIRED_FIELDS = {
    "id",
    "text",
    "label",
    "category",
    "language",
    "difficulty",
    "rationale",
    "scenario_group",
}
VALID_LABELS = {"BENIGN", "SUSPICIOUS", "MALICIOUS"}


def load(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_number}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(record, dict):
            errors.append(f"{path.name}:{line_number}: record is not an object")
            continue
        missing = sorted(REQUIRED_FIELDS - record.keys())
        if missing:
            errors.append(f"{path.name}:{line_number}: missing fields {missing}")
        if record.get("label") not in VALID_LABELS:
            errors.append(f"{path.name}:{line_number}: invalid label {record.get('label')!r}")
        if not isinstance(record.get("text"), str) or not record.get("text", "").strip():
            errors.append(f"{path.name}:{line_number}: empty or non-string text")
        records.append(record)
    return records, errors


def duplicates(records: list[dict[str, Any]], field: str) -> list[str]:
    seen: set[Any] = set()
    duplicates_found: list[str] = []
    for record in records:
        value = record.get(field)
        if value in seen:
            duplicates_found.append(str(value))
        seen.add(value)
    return sorted(set(duplicates_found))


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    dev, dev_errors = load(DEV_PATH)
    test, test_errors = load(TEST_PATH)
    dev_ids = {record.get("id") for record in dev}
    test_ids = {record.get("id") for record in test}
    dev_texts = {record.get("text") for record in dev}
    test_texts = {record.get("text") for record in test}
    result = {
        "datasets": {"dev": DEV_PATH.name, "test": TEST_PATH.name},
        "counts": {"dev": len(dev), "test": len(test)},
        "errors": {"dev": dev_errors, "test": test_errors},
        "duplicate_ids": {"dev": duplicates(dev, "id"), "test": duplicates(test, "id")},
        "duplicate_texts": {
            "dev": duplicates(dev, "text"),
            "test": duplicates(test, "text"),
        },
        "cross_split_exact_duplicates": {
            "ids": sorted(str(value) for value in dev_ids & test_ids),
            "texts": sorted(str(value) for value in dev_texts & test_texts),
        },
        "label_counts": {
            "dev": dict(sorted(Counter(record.get("label") for record in dev).items())),
            "test": dict(sorted(Counter(record.get("label") for record in test).items())),
        },
        "category_counts": {
            "dev": dict(sorted(Counter(record.get("category") for record in dev).items())),
            "test": dict(sorted(Counter(record.get("category") for record in test).items())),
        },
        "language_counts": {
            "dev": dict(sorted(Counter(record.get("language") for record in dev).items())),
            "test": dict(sorted(Counter(record.get("language") for record in test).items())),
        },
        "human_review_items": [],
    }
    result["human_review_items"].extend(
        "Cross-split exact duplicate IDs exist; verify split generation provenance."
        for _ in result["cross_split_exact_duplicates"]["ids"]
    )
    result["human_review_items"].extend(
        "Cross-split exact duplicate texts exist; assess potential leakage."
        for _ in result["cross_split_exact_duplicates"]["texts"]
    )
    REPORT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Evaluation Dataset v2 Audit",
        "",
        f"Development records: {len(dev)}; held-out records: {len(test)}.",
        f"Validation errors: {len(dev_errors) + len(test_errors)}.",
        f"Cross-split duplicate IDs: {len(result['cross_split_exact_duplicates']['ids'])}.",
        f"Cross-split duplicate texts: {len(result['cross_split_exact_duplicates']['texts'])}.",
        "",
        "The audit is read-only. Existing JSONL files were not changed.",
        "",
        "## Human review items",
        "",
    ]
    lines.extend(f"- {item}" for item in result["human_review_items"])
    if not result["human_review_items"]:
        lines.append("- None detected by the mechanical checks.")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"dev": len(dev), "test": len(test), "errors": len(dev_errors) + len(test_errors)}
        )
    )
    print(f"Reports: {REPORT_JSON}, {REPORT_MD}")
    return 0 if not dev_errors and not test_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
