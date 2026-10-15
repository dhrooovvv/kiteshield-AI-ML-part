from __future__ import annotations

import math

import pytest

from app.ai_ml.experimental_decision_policy import (
    ExperimentalClassification,
    NormalizedDetectorOutput,
    decide,
    unavailable_detector,
)


def signal(name: str, attack: bool, score: float = 0.8) -> NormalizedDetectorOutput:
    return NormalizedDetectorOutput(name=name, predicted_attack=attack, score=score)


def test_horizon_first_never_allows_horizon_attack() -> None:
    result = decide(
        "horizon_first_risk_based",
        horizon=signal("horizon", True),
        bastion=signal("bastion", False, 0.01),
        rules=signal("rules", False, 0.5),
    )

    assert result.classification is ExperimentalClassification.ATTACK
    assert result.reason_code == "horizon_preserved"


def test_disagreement_escalates_instead_of_allowing() -> None:
    result = decide(
        "disagreement_review",
        horizon=signal("horizon", True),
        bastion=signal("bastion", False, 0.01),
        rules=signal("rules", False, 0.5),
    )

    assert result.classification is ExperimentalClassification.REVIEW
    assert result.counts_as_attack
    assert result.recommended_next_step == "escalate_for_review"


def test_unavailable_signal_fails_closed_explicitly() -> None:
    result = decide(
        "horizon_or_bastion",
        horizon=unavailable_detector("horizon", "model_load_failed"),
        bastion=signal("bastion", False, 0.01),
        rules=signal("rules", False, 0.5),
    )

    assert result.classification is ExperimentalClassification.ERROR
    assert result.risk_tier.value == "ERROR"
    assert result.counts_as_attack


@pytest.mark.parametrize("score", [-0.1, 1.1, math.inf, math.nan])
def test_non_finite_or_out_of_range_scores_are_rejected(score: float) -> None:
    with pytest.raises(ValueError):
        signal("test", False, score)


def test_three_layer_or_requires_no_production_authority() -> None:
    result = decide(
        "three_layer_or",
        horizon=signal("horizon", False, 0.1),
        bastion=signal("bastion", False, 0.1),
        rules=signal("rules", True, 0.8),
    )

    assert result.classification is ExperimentalClassification.ATTACK
    assert result.recommended_next_step == "retain_policy_checks"
