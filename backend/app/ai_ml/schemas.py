"""Typed contracts for AI/ML safety signals.

These results are advisory only. They must not be used as a substitute for
the deterministic policy engine or signer checks.
"""

from dataclasses import dataclass
from enum import StrEnum


class InjectionLabel(StrEnum):
    """Classification labels produced by the deterministic screen."""

    BENIGN = "BENIGN"
    SUSPICIOUS = "SUSPICIOUS"
    MALICIOUS = "MALICIOUS"


@dataclass(frozen=True)
class InjectionScreenResult:
    """Safe-to-log result for one untrusted text item.

    ``confidence`` is a deterministic heuristic score, not a calibrated
    probability. ``matched_signals`` contains rule identifiers rather than
    the original text, preventing accidental sensitive-text logging.
    """

    label: InjectionLabel
    confidence: float
    matched_signals: tuple[str, ...]
    model_version: str = "rules-v1"

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
