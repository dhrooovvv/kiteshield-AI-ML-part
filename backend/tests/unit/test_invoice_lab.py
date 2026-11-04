"""Pure lab regressions: no model requests and no held-out evaluation execution."""

import json
import math
import random
import statistics
from collections import Counter
from contextlib import nullcontext
from unittest.mock import AsyncMock

import pytest

from scripts import invoice_lab as lab


def measured(kind="benign", **overrides):
    row = {
        "kind": kind, "measurement_valid": True, "state": "SIMULATED",
        "simulated_payment": True, "wrong_payee": False,
        "field_matches": dict.fromkeys(lab.FIELDS, True),
        "first_stop": None, "without_layer": {}, "pipeline_ms": 120, "extraction_ms": 100,
    }
    return {**row, **overrides}


def test_wilson_known_interval_and_empty_sample():
    assert lab.wilson95(5, 10) == pytest.approx([0.2365930905, 0.7634069095])
    assert lab.wilson95(0, 0) is None
    assert lab.rate(0, 0) == {"count": 0, "denominator": 0, "rate": None, "wilson95": None}


def test_zero_observed_failures_does_not_claim_zero_risk():
    interval = lab.wilson95(0, 60)
    assert interval[0] == pytest.approx(0, abs=1e-12)
    assert interval[1] == pytest.approx(0.0601718521)
    assert lab.wilson95(60, 60)[0] < 1


@pytest.mark.parametrize("successes,total", [(-1, 5), (6, 5), (0, -1)])
def test_wilson_rejects_invalid_counts(successes, total):
    with pytest.raises(ValueError):
        lab.wilson95(successes, total)


def test_nearest_rank_p95_and_mean_exclude_missing_latencies():
    result = lab.latency_summary([*range(1, 101), None])
    assert result["n"] == 100
    assert result["mean_ms"] == 50.5
    assert result["p95_ms"] == 95
    single = lab.latency_summary([12])
    assert single["mean_ci95_ms"] == [12, 12]
    assert single["p95_ci95_ms"] == [12, 12]
    empty = lab.latency_summary([])
    assert empty["n"] == 0
    assert all(empty[key] is None for key in (
        "mean_ms", "p95_ms", "mean_ci95_ms", "p95_ci95_ms"))


def test_bootstrap_intervals_are_seeded_order_invariant_and_leave_global_rng_untouched():
    state = random.getstate()
    result = lab.latency_summary([10, 20, 30, 40, 100, None])
    assert random.getstate() == state
    assert result == lab.latency_summary([100, 40, 30, 20, 10])
    assert result["bootstrap"]["seed"] == 42
    assert result["bootstrap"]["resamples"] == 2000
    rng = random.Random(42)  # noqa: S311 -- independent deterministic bootstrap reference
    samples = [rng.choices([10, 20, 30, 40, 100], k=5) for _ in range(2000)]
    mean_quantiles = statistics.quantiles([sum(sample) / 5 for sample in samples],
                                         n=40, method="inclusive")
    p95_quantiles = statistics.quantiles([max(sample) for sample in samples],
                                        n=40, method="inclusive")
    assert result["mean_ci95_ms"] == [mean_quantiles[0], mean_quantiles[-1]]
    assert result["p95_ci95_ms"] == [p95_quantiles[0], p95_quantiles[-1]]


def test_percentile_ci_interpolates_endpoints():
    # Two observations make the resampled means exactly 0, 5 or 10.
    result = lab.latency_summary([0, 10])
    assert result["mean_ci95_ms"] == [0, 10]
    assert result["p95_ci95_ms"] == [0, 10]


def test_per_layer_catches_overlap_but_multiple_reasons_in_one_layer_count_once():
    rows = [measured("attack", first_stop="registry", reasons=[
        {"layer": "registry", "code": "A"}, {"layer": "registry", "code": "B"},
        {"layer": "screening", "code": "C"}, {"layer": "policy", "code": "D"},
    ]), measured("attack", first_stop="screening", reasons=[
        {"layer": "screening", "code": "E"},
    ]), {"measurement_valid": False, "reasons": [{"layer": "policy", "code": "X"}]}]
    summary = lab.summarize(rows)
    assert summary["per_layer_catch_count"] == {
        "extraction_validator": 0, "registry": 1, "screening": 2, "policy": 1,
    }
    assert summary["first_stop_count"] == {"registry": 1, "screening": 1}


@pytest.mark.parametrize("value", [-1, math.inf, math.nan])
def test_invalid_latency_is_not_reported_as_a_measurement(value):
    with pytest.raises(ValueError):
        lab.latency_summary([value])


def test_extraction_scores_four_exact_fields_without_float_rounding():
    expected = dict(vendor_name="Northstar Services", invoice_number="DEV-1",
                    amount_eth="0.000000000000000001", due_date="2026-10-24")
    assert all(lab.extraction_matches(expected, expected).values())
    assert not any(lab.extraction_matches(expected, None).values())
    changed = {**expected, "amount_eth": "0.000000000000000002"}
    assert lab.extraction_matches(expected, changed) == {
        "vendor_name": True, "invoice_number": True, "amount_eth": False, "due_date": True,
    }


def test_invalid_extraction_keeps_every_counterfactual_unknown():
    checks = lab.unknown_checks()
    assert checks["first_stop"] == "extraction_validator"
    assert set(checks["without_layer"]) == set(lab.LAYERS)
    assert all(value["would_pass_checks"] is None for value in checks["without_layer"].values())
    assert not any(value["would_pass_checks"] is True
                   for value in checks["without_layer"].values())


def test_metrics_separate_benign_attacks_runtime_errors_and_payee_denominators():
    invalid = measured(state="NEEDS_HUMAN_REVIEW", simulated_payment=False,
                       field_matches=dict.fromkeys(lab.FIELDS, False), **lab.unknown_checks())
    runtime = {"kind": "benign", "measurement_valid": False}
    rows = [measured(), invalid, measured("attack", wrong_payee=True), runtime]
    summary = lab.summarize(rows)
    assert summary["runtime_errors"] == 1
    assert summary["measured"] == 3
    assert summary["benign_all_four_correct"]["rate"] == .5
    assert summary["benign_field_micro_accuracy"]["denominator"] == 8
    assert summary["benign_false_block"]["rate"] == .5
    assert summary["attack_simulated_payment"]["rate"] == 1
    assert summary["wrong_payee"]["denominator"] == 2
    assert summary["wrong_payee"]["count"] == 1
    assert summary["first_stop_count"] == {"none": 2, "extraction_validator": 1}
    assert summary["counterfactual_unknown"] == 4


def test_empty_summary_has_no_invented_perfect_rates_or_latencies():
    summary = lab.summarize([])
    assert summary["benign_false_block"]["rate"] is None
    assert summary["wrong_payee"]["rate"] is None
    assert summary["pipeline_latency"]["mean_ms"] is None


def test_one_shot_marker_is_exclusive_and_keeps_original_metadata(tmp_path):
    marker = tmp_path / "evaluation.started"
    lab.claim_evaluation(marker, {"source_sha": "first"})
    with pytest.raises(FileExistsError):
        lab.claim_evaluation(marker, {"source_sha": "replacement"})
    assert json.loads(marker.read_text()) == {"source_sha": "first"}


def test_atomic_partial_report_replacement_and_cleanup(tmp_path):
    destination = tmp_path / "reports" / "lab.json"
    lab.persist(destination, {"status": "running", "attempts": [1]})
    assert json.loads(destination.read_text())["attempts"] == [1]
    with pytest.raises(ValueError):
        lab.persist(destination, {"latency": math.nan})
    assert json.loads(destination.read_text())["attempts"] == [1]
    lab.persist(destination, {"status": "partial", "attempts": [1, 2]})
    assert json.loads(destination.read_text())["attempts"] == [1, 2]
    assert list(destination.parent.iterdir()) == [destination]


def test_benchmark_is_five_development_cases_and_duplicate_seed_is_explicit():
    cases = lab.benchmark_cases()
    assert len(cases) == 5
    assert len({case["id"] for case in cases}) == 5
    assert Counter(case["kind"] for case in cases) == {"benign": 1, "attack": 4}
    assert all(case["id"].startswith("development-") for case in cases)
    duplicate = next(case for case in cases if case["duplicate_seed"])
    assert lab.duplicate_number(duplicate) in duplicate["text"]


def test_duplicate_heldout_identity_comes_from_document_not_model_output():
    assert lab.duplicate_number({"text": "Invoice: DUP-007\nCopy"}) == "DUP-007"
    with pytest.raises(ValueError):
        lab.duplicate_number({"text": "No deterministic identity"})


def test_frozen_dataset_loader_rejects_uncommitted_changes(tmp_path, monkeypatch):
    for name in ("heldout.jsonl", "manifest.json", "README.md"):
        (tmp_path / name).write_text("immutable fixture")
    monkeypatch.setattr(lab, "DATASET", tmp_path)
    monkeypatch.setattr(lab, "git", lambda *args: b"different committed bytes")
    with pytest.raises(RuntimeError, match="differs from committed"):
        lab.load_frozen_dataset()


def test_clock_is_fixed_without_changing_real_latency_clock():
    assert lab.LabClock.now(lab.UTC).isoformat() == lab.CLOCK
    assert lab.LabClock.now().tzinfo is None


def test_cli_requires_exactly_one_mode_without_running_any_lab():
    with pytest.raises(SystemExit) as absent:
        lab.main([])
    assert absent.value.code == 2
    with pytest.raises(SystemExit) as conflicting:
        lab.main(["--evaluate", "--benchmark"])
    assert conflicting.value.code == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("category", lab.CATEGORIES)
async def test_generated_note_is_preserved_and_invoice_identity_is_owned_by_code(monkeypatch,
                                                                               category):
    from app.services import invoice_llm

    note = "  A harmless generated note; do not replace me to force a block.  "
    request = AsyncMock(return_value=({"text": note}, 15))
    monkeypatch.setattr(invoice_llm, "request_json", request)
    case = await lab.generate_attack(category, 3)
    assert case["text"] == (
        "Vendor: Northstar Services\nInvoice: RT-LAB-3\nAmount: 0.00001 ETH\n"
        "Due date: 2026-10-24\n" + note)
    assert case["attack_note"] == note
    assert case["seed_invoice_number"] == "RT-LAB-3"
    assert case["duplicate_seed"] is (category == "duplicate")
    schema = request.call_args.args[2]
    assert set(schema["properties"]) == {"text"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["text"]["maxLength"] == 700
    assert "0x" + "2" * 40 in request.call_args.args[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [{"text": "x", "invoice_number": "MODEL-ID"},
                                   {"text": "x" * 701}, {"text": "   "},
                                   {"text": 123}, {}])
async def test_invalid_generation_is_rejected_without_an_invented_note(monkeypatch, raw):
    from app.services import invoice_llm

    monkeypatch.setattr(invoice_llm, "request_json", AsyncMock(return_value=(raw, 1)))
    with pytest.raises(ValueError):
        await lab.generate_attack("address_swap", 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_count", [1, 7])
async def test_generation_failures_continue_and_finish_partial_without_pipeline_fallback(
        monkeypatch, tmp_path, failure_count):
    monkeypatch.setattr(lab, "configure_environment", lambda _: None)
    monkeypatch.setattr(lab, "isolated_runtime", lambda: nullcontext([]))
    monkeypatch.setattr(lab, "model_identity", AsyncMock(return_value={"name": "mock-model"}))
    monkeypatch.setattr(lab, "fingerprints", lambda: {"source": "fixed"})

    async def generate(category, index):
        if index < failure_count:
            raise ValueError("synthetic generation failure")
        return {"id": f"red-team-{category}", "category": category, "kind": "attack",
                "text": "successful synthetic note"}

    async def pipeline(case, _directory):
        return {**measured("attack"), "id": case["id"], "category": case["category"]}

    generator = AsyncMock(side_effect=generate)
    pipeline_mock = AsyncMock(side_effect=pipeline)
    monkeypatch.setattr(lab, "generate_attack", generator)
    monkeypatch.setattr(lab, "run_case", pipeline_mock)
    report = {"attempts": [], "summary": lab.summarize([]), "status": "running"}
    output = tmp_path / "redteam.json"
    await lab.run("red-team", output, report, None, {"source": "fixed"})
    saved = json.loads(output.read_text())
    assert generator.await_count == 7
    assert pipeline_mock.await_count == 7 - failure_count
    assert saved["status"] == saved["phase"] == "partial"
    assert len(saved["attempts"]) == 7
    assert saved["summary"]["measured"] == 7 - failure_count
    assert saved["summary"]["runtime_errors"] == failure_count
    for failure in saved["generation_failures"]:
        assert failure["first_stop"] is None and failure["reasons"] == []
        assert failure["measurement_valid"] is False
        assert all(item["would_pass_checks"] is None
                   for item in failure["without_layer"].values())
