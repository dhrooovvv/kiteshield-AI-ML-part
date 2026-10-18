"""Experimental, non-production decision policies for detector experiments.

This module only combines normalized advisory signals. It cannot authorize a
transaction, issue capability tokens, or override policy or signer checks.
Detector failures produce an explicit review/error outcome rather than a
benign result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class ExperimentalClassification(StrEnum):
    BENIGN = "BENIGN"
    ATTACK = "ATTACK"
    REVIEW = "REVIEW"
    ERROR = "ERROR"


class RiskTier(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    REVIEW = "REVIEW"
    ERROR = "ERROR"


@dataclass(frozen=True)
class NormalizedDetectorOutput:
    """One detector's normalized advisory output."""

    name: str
    predicted_attack: bool
    score: float | None = None
    model_version: str | None = None
    available: bool = True
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.score is not None and (
            not math.isfinite(self.score) or not 0.0 <= self.score <= 1.0
        ):
            raise ValueError("score must be finite and between 0 and 1")
        if not self.available and not self.error_code:
            raise ValueError("unavailable detector output requires error_code")


@dataclass(frozen=True)
class ExperimentalDecision:
    """Structured result for offline policy evaluation only."""

    strategy: str
    classification: ExperimentalClassification
    risk_tier: RiskTier
    reason_code: str
    recommended_next_step: str
    horizon_prediction: bool
    bastion_prediction: bool
    rules_prediction: bool
    model_agreement: bool | None
    fallback_used: bool
    detector_versions: tuple[tuple[str, str | None], ...]

    @property
    def counts_as_attack(self) -> bool:
        """Treat review/error as positive for conservative offline metrics."""
        return self.classification in {
            ExperimentalClassification.ATTACK,
            ExperimentalClassification.REVIEW,
            ExperimentalClassification.ERROR,
        }


def unavailable_detector(name: str, error_code: str) -> NormalizedDetectorOutput:
    """Create an explicit unavailable signal for failure-path experiments."""
    return NormalizedDetectorOutput(
        name=name,
        predicted_attack=False,
        available=False,
        error_code=error_code,
    )


def decide(
    strategy: str,
    *,
    horizon: NormalizedDetectorOutput,
    bastion: NormalizedDetectorOutput,
    rules: NormalizedDetectorOutput,
) -> ExperimentalDecision:
    """Apply an experimental strategy to normalized detector outputs.

    ``horizon_first_risk_based`` preserves any Horizon attack. When Horizon is
    benign, Bastion and rules must agree before producing an attack result.
    ``disagreement_review`` makes disagreement explicit and never treats it as
    proof of safety.
    """
    outputs = (horizon, bastion, rules)
    versions = tuple((output.name, output.model_version) for output in outputs)
    unavailable = tuple(output for output in outputs if not output.available)
    if unavailable:
        return ExperimentalDecision(
            strategy=strategy,
            classification=ExperimentalClassification.ERROR,
            risk_tier=RiskTier.ERROR,
            reason_code="detector_unavailable",
            recommended_next_step="fail_closed_and_escalate",
            horizon_prediction=horizon.predicted_attack,
            bastion_prediction=bastion.predicted_attack,
            rules_prediction=rules.predicted_attack,
            model_agreement=None,
            fallback_used=False,
            detector_versions=versions,
        )

    if strategy == "horizon_only":
        attack = horizon.predicted_attack
        reason = "horizon_positive" if attack else "horizon_negative"
    elif strategy == "bastion_only":
        attack = bastion.predicted_attack
        reason = "bastion_positive" if attack else "bastion_negative"
    elif strategy == "rules_only":
        attack = rules.predicted_attack
        reason = "rules_positive" if attack else "rules_negative"
    elif strategy == "horizon_or_bastion":
        attack = horizon.predicted_attack or bastion.predicted_attack
        reason = "horizon_or_bastion_positive" if attack else "both_negative"
    elif strategy == "horizon_and_bastion":
        attack = horizon.predicted_attack and bastion.predicted_attack
        reason = "horizon_and_bastion_positive" if attack else "not_both_positive"
    elif strategy == "horizon_first_risk_based":
        attack = horizon.predicted_attack or (bastion.predicted_attack and rules.predicted_attack)
        reason = "horizon_preserved" if horizon.predicted_attack else "bastion_rules_confirmation"
        if not attack:
            reason = "horizon_negative_no_confirmation"
    elif strategy == "disagreement_review":
        disagreement = horizon.predicted_attack != bastion.predicted_attack
        if disagreement:
            return ExperimentalDecision(
                strategy=strategy,
                classification=ExperimentalClassification.REVIEW,
                risk_tier=RiskTier.REVIEW,
                reason_code="model_disagreement",
                recommended_next_step="escalate_for_review",
                horizon_prediction=horizon.predicted_attack,
                bastion_prediction=bastion.predicted_attack,
                rules_prediction=rules.predicted_attack,
                model_agreement=False,
                fallback_used=False,
                detector_versions=versions,
            )
        attack = horizon.predicted_attack
        reason = "models_agree_positive" if attack else "models_agree_negative"
    elif strategy == "three_layer_or":
        if rules.predicted_attack:
            attack = True
            reason = "rules_positive"
        elif horizon.predicted_attack and bastion.predicted_attack:
            attack = True
            reason = "both_models_positive"
        elif horizon.predicted_attack or bastion.predicted_attack:
            return ExperimentalDecision(
                strategy=strategy,
                classification=ExperimentalClassification.REVIEW,
                risk_tier=RiskTier.REVIEW,
                reason_code="model_disagreement",
                recommended_next_step="escalate_for_review",
                horizon_prediction=horizon.predicted_attack,
                bastion_prediction=bastion.predicted_attack,
                rules_prediction=rules.predicted_attack,
                model_agreement=False,
                fallback_used=False,
                detector_versions=versions,
            )
        else:
            attack = False
            reason = "all_negative"
    elif strategy == "horizon_threshold_bastion":
        attack = horizon.predicted_attack or bastion.predicted_attack
        reason = "horizon_threshold_or_bastion" if attack else "both_negative"
    else:
        raise ValueError(f"unknown experimental strategy: {strategy}")

    classification = (
        ExperimentalClassification.ATTACK if attack else ExperimentalClassification.BENIGN
    )
    return ExperimentalDecision(
        strategy=strategy,
        classification=classification,
        risk_tier=RiskTier.HIGH if attack else RiskTier.LOW,
        reason_code=reason,
        recommended_next_step="retain_policy_checks" if attack else "retain_policy_checks",
        horizon_prediction=horizon.predicted_attack,
        bastion_prediction=bastion.predicted_attack,
        rules_prediction=rules.predicted_attack,
        model_agreement=horizon.predicted_attack == bastion.predicted_attack,
        fallback_used=False,
        detector_versions=versions,
    )
