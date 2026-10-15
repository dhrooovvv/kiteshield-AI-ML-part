"""Write detector-specific error reports from the advanced benchmark output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "reports"
RESULT_PATH = REPORT_DIR / "advanced_detection_evaluation_v2.json"


def markdown(detector: str, report: dict[str, Any]) -> str:
    errors = report["errors"]
    metrics = report["metrics"]
    lines = [
        f"# {detector.title()} Error Analysis v2",
        "",
        "Generated from the existing held-out evaluation output. This report is descriptive only; "
        "it does not tune or modify the detector.",
        "",
        f"Metrics: TP={metrics['true_positive']}, FP={metrics['false_positive']}, "
        f"TN={metrics['true_negative']}, FN={metrics['false_negative']}; "
        f"precision={metrics['precision']:.4f}, recall={metrics['recall']:.4f}, "
        f"F1={metrics['f1']:.4f}, FPR={metrics['false_positive_rate']:.4f}, "
        f"FNR={metrics['false_negative_rate']:.4f}.",
        "",
        "## Error summary by category",
        "",
        "| Category | Count | False positives | False negatives |",
        "|---|---:|---:|---:|",
    ]
    for category, values in report["by_category"].items():
        lines.append(
            f"| {category} | {values['count']} | {values['false_positive']} | "
            f"{values['false_negative']} |"
        )
    for kind in ("false_positive", "false_negative"):
        lines.extend(["", f"## {kind.replace('_', ' ').title()}s", ""])
        if not errors[kind]:
            lines.append("None.")
            continue
        lines.extend(
            [
                "| ID | Truth | Predicted | Score | Category | Language | Difficulty |",
                "|---|---|---|---:|---|---|---|",
            ]
        )
        for item in errors[kind]:
            lines.append(
                f"| {item['id']} | {item['ground_truth']} | {item['predicted']} | "
                f"{item['score']:.6f} | {item['category']} | {item['language']} | "
                f"{item['difficulty']} |"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    data = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    test = data["test"]
    for detector, strategy in (("horizon", "horizon_only"), ("bastion", "bastion_only")):
        errors = test["error_analysis"][detector]
        report = {
            "detector": detector,
            "source": str(RESULT_PATH),
            "metrics": test["strategies"][strategy]["metrics"],
            "by_category": test["strategies"][strategy]["by_category"],
            "by_language": test["strategies"][strategy]["by_language"],
            "by_difficulty": test["strategies"][strategy]["by_difficulty"],
            "errors": errors,
        }
        json_path = REPORT_DIR / f"{detector}_error_analysis_v2.json"
        md_path = REPORT_DIR / f"{detector}_error_analysis_v2.md"
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        md_path.write_text(markdown(detector, report), encoding="utf-8")
        print(json_path)
        print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
