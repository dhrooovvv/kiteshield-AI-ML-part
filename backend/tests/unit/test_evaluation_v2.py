"""Validation tests for the synthetic v2 evaluation data and benchmark helpers."""

from pathlib import Path

import pytest

from scripts.benchmark_evaluation_v2 import Counts, calculate_metrics, report_predictions, run_rules
from scripts.generate_evaluation_v2 import (
    REQUIRED_FIELDS,
    grouped_split,
    load_records,
    validate_records,
)

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "app" / "ai_ml" / "evaluation_dataset_v2.jsonl"
DEV = ROOT / "app" / "ai_ml" / "evaluation_dev_v2.jsonl"
TEST = ROOT / "app" / "ai_ml" / "evaluation_test_v2.jsonl"


def test_v2_dataset_schema_and_size() -> None:
    records = load_records(DATASET)

    assert len(records) >= 1000
    assert all(set(record) == REQUIRED_FIELDS for record in records)
    assert {record["label"] for record in records} == {"BENIGN", "SUSPICIOUS", "MALICIOUS"}


def test_v2_ids_and_texts_are_unique() -> None:
    records = load_records(DATASET)

    assert len({record["id"] for record in records}) == len(records)
    assert len({record["text"] for record in records}) == len(records)


def test_duplicate_ids_and_texts_are_rejected() -> None:
    records = load_records(DATASET)[:2]
    duplicate_id = [records[0], {**records[1], "id": records[0]["id"]}]
    duplicate_text = [records[0], {**records[1], "text": records[0]["text"]}]

    with pytest.raises(ValueError, match="IDs must be unique|IDs"):
        validate_records(duplicate_id)
    with pytest.raises(ValueError, match="texts must be unique"):
        validate_records(duplicate_text)


def test_split_files_are_disjoint_and_complete() -> None:
    records = load_records(DATASET)
    dev = load_records(DEV)
    test = load_records(TEST)
    all_ids = {record["id"] for record in records}

    assert not ({record["id"] for record in dev} & {record["id"] for record in test})
    assert {record["id"] for record in dev} | {record["id"] for record in test} == all_ids
    assert {record["category"] for record in test} == {record["category"] for record in records}


def test_grouped_split_is_reproducible_and_keeps_families_together() -> None:
    records = load_records(DATASET)
    first_dev, first_test = grouped_split(records)
    second_dev, second_test = grouped_split(records)

    assert [record["id"] for record in first_dev] == [record["id"] for record in second_dev]
    assert [record["id"] for record in first_test] == [record["id"] for record in second_test]
    assert not (
        {record["scenario_group"] for record in first_dev}
        & {record["scenario_group"] for record in first_test}
    )


def test_metric_edge_cases_and_prediction_separation() -> None:
    all_negative = calculate_metrics(Counts(true_negative=3))
    assert all_negative["precision"] == 0.0
    assert all_negative["recall"] == 0.0
    assert all_negative["false_positive_rate"] == 0.0

    records = [
        {
            "id": "x",
            "text": "plain note",
            "label": "BENIGN",
            "category": "x",
            "language": "English",
            "difficulty": "easy",
            "rationale": "x",
            "scenario_group": "x",
        }
    ]
    report = report_predictions(records, [True], [0.1])
    assert report["metrics"]["false_positive"] == 1
    assert report["metrics"]["true_positive"] == 0


def test_rules_only_path_does_not_require_model_loading() -> None:
    records = load_records(DATASET)[:3]

    predictions, latencies = run_rules(records)

    assert len(predictions) == len(records)
    assert len(latencies) == len(records)
