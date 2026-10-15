"""Audit the fresh v3 dataset against the existing v1/v2 datasets."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "app" / "ai_ml" / "evaluation_final_v3.jsonl"
REFERENCE_PATHS = (
    PROJECT_ROOT / "app" / "ai_ml" / "evaluation_dataset_v1.jsonl",
    PROJECT_ROOT / "app" / "ai_ml" / "evaluation_dev_v2.jsonl",
    PROJECT_ROOT / "app" / "ai_ml" / "evaluation_test_v2.jsonl",
)
REPORT_DIR = PROJECT_ROOT / "reports"
JSON_REPORT = REPORT_DIR / "evaluation_final_v3_audit.json"
MD_REPORT = REPORT_DIR / "evaluation_final_v3_audit.md"
REQUIRED_FIELDS = {"id", "label", "category", "text"}
VALID_LABELS = {"BENIGN", "SUSPICIOUS", "MALICIOUS"}
NEAR_DUPLICATE_THRESHOLD = 0.86


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()


def token_jaccard(left: str, right: str) -> float:
    a, b = set(normalize(left).split()), set(normalize(right).split())
    return len(a & b) / len(a | b) if a or b else 1.0


def main() -> int:
    rows = load_jsonl(DATASET)
    references = [row for path in REFERENCE_PATHS if path.exists() for row in load_jsonl(path)]
    errors: list[str] = []
    ids: set[str] = set()
    exact_matches: list[dict[str, str]] = []
    near_matches: list[dict[str, Any]] = []
    reference_texts = {normalize(row["text"]): row["id"] for row in references}

    for index, row in enumerate(rows, start=1):
        missing = REQUIRED_FIELDS - row.keys()
        if missing:
            errors.append(f"row {index}: missing fields {sorted(missing)}")
        if row.get("id") in ids:
            errors.append(f"row {index}: duplicate id {row.get('id')}")
        ids.add(row.get("id", ""))
        if row.get("label") not in VALID_LABELS:
            errors.append(f"row {index}: invalid label {row.get('label')!r}")
        if not isinstance(row.get("text"), str) or not row.get("text", "").strip():
            errors.append(f"row {index}: empty or invalid text")
        normalized = normalize(row.get("text", ""))
        if normalized in reference_texts:
            exact_matches.append({"v3_id": row["id"], "reference_id": reference_texts[normalized]})

    for row in rows:
        for reference in references:
            sequence = SequenceMatcher(
                None, normalize(row["text"]), normalize(reference["text"])
            ).ratio()
            jaccard = token_jaccard(row["text"], reference["text"])
            if sequence >= NEAR_DUPLICATE_THRESHOLD or jaccard >= NEAR_DUPLICATE_THRESHOLD:
                near_matches.append(
                    {
                        "v3_id": row["id"],
                        "reference_id": reference["id"],
                        "sequence_ratio": round(sequence, 4),
                        "token_jaccard": round(jaccard, 4),
                    }
                )

    labels = {
        label: sum(row.get("label") == label for row in rows) for label in sorted(VALID_LABELS)
    }
    categories: dict[str, dict[str, int]] = {}
    for row in rows:
        category = row.get("category", "<missing>")
        categories.setdefault(category, {label: 0 for label in sorted(VALID_LABELS)})
        categories[category][row.get("label", "<missing>")] = (
            categories[category].get(row.get("label", "<missing>"), 0) + 1
        )
    payload = DATASET.read_bytes()
    report = {
        "dataset": str(DATASET),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "record_count": len(rows),
        "labels": labels,
        "categories": dict(sorted(categories.items())),
        "reference_files": [str(path) for path in REFERENCE_PATHS if path.exists()],
        "reference_record_count": len(references),
        "near_duplicate_threshold": NEAR_DUPLICATE_THRESHOLD,
        "exact_matches": exact_matches,
        "near_matches": near_matches,
        "errors": errors,
        "independence_supported": not exact_matches and not near_matches and not errors,
        "method": "Normalized exact comparison plus SequenceMatcher and token-Jaccard "
        "screening against available v1/v2 records.",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Final v3 Dataset Audit",
        "",
        f"Records: `{len(rows)}`; SHA-256: `{report['sha256']}`.",
        f"Labels: `{labels}`.",
        f"Independence supported by this audit: `{report['independence_supported']}`.",
        "",
        "## Independence method",
        "",
        report["method"],
        "",
        "## Category distribution",
        "",
        "| Category | BENIGN | MALICIOUS | SUSPICIOUS | Total |",
        "|---|---:|---:|---:|---:|",
    ]
    for category, counts in sorted(categories.items()):
        lines.append(
            f"| {category} | {counts.get('BENIGN', 0)} | {counts.get('MALICIOUS', 0)} | "
            f"{counts.get('SUSPICIOUS', 0)} | {sum(counts.values())} |"
        )
    lines.extend(
        [
            "",
            f"Exact matches: `{len(exact_matches)}`.",
            f"Near matches: `{len(near_matches)}`.",
            f"Schema errors: `{len(errors)}`.",
            "",
        ]
    )
    MD_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "records": len(rows),
                "sha256": report["sha256"],
                "exact_matches": len(exact_matches),
                "near_matches": len(near_matches),
                "errors": len(errors),
                "independence_supported": report["independence_supported"],
            }
        )
    )
    return 0 if report["independence_supported"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
