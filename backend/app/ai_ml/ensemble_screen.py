"""Live prompt-injection screening using rules, Horizon, and Bastion.

This service is a screening gate only. It cannot authorize an action, issue a
capability, sign a transaction, or submit a transaction.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

from app.ai_ml.experimental_decision_policy import (
    ExperimentalClassification,
    NormalizedDetectorOutput,
    decide,
)
from app.ai_ml.schemas import InjectionLabel, InjectionScreenResult
from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class EnsembleScreenResult:
    """Normalized, non-authorizing result from all required detectors."""

    classification: ExperimentalClassification
    reason_code: str
    rules: InjectionScreenResult
    horizon_attack: bool
    horizon_score: float | None
    bastion_attack: bool
    bastion_score: float | None
    detector_versions: tuple[tuple[str, str | None], ...]
    latency_ms: float


@dataclass(frozen=True)
class _LoadedHorizon:
    tokenizer: Any
    model: Any
    device: Any
    injection_id: int
    model_version: str


@dataclass(frozen=True)
class _LoadedBastion:
    guard: Any
    model_version: str


class PromptInjectionEnsemble:
    """Concurrency-safe lazy ensemble for the live agent boundary."""

    def __init__(
        self,
        rules_detector: Any | None = None,
        settings: Settings | None = None,
    ) -> None:
        from app.ai_ml.injection_screen import InjectionScreen

        self._rules = rules_detector or InjectionScreen()
        self._settings = settings or get_settings()
        self._horizon: _LoadedHorizon | None = None
        self._bastion: _LoadedBastion | None = None
        self._load_lock = asyncio.Lock()

    async def screen(self, text: str) -> EnsembleScreenResult:
        """Screen text and fail closed if a required model is unavailable."""
        started_ns = time.perf_counter_ns()
        if not isinstance(text, str) or len(text) > self._settings.ai_ml_max_prompt_length:
            raise RuntimeError("prompt screening input is invalid or too large")

        rules = self._rules.screen(text)
        if not isinstance(rules, InjectionScreenResult):
            raise RuntimeError("rules detector returned malformed output")

        # A confirmed rule attack is sufficient to reject safely. Benign rules
        # output must still pass both model detectors before continuing.
        if rules.label != InjectionLabel.BENIGN:
            return EnsembleScreenResult(
                classification=ExperimentalClassification.ATTACK,
                reason_code="rules_positive",
                rules=rules,
                horizon_attack=False,
                horizon_score=None,
                bastion_attack=False,
                bastion_score=None,
                detector_versions=(("rules", rules.model_version),),
                latency_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
            )

        try:
            await asyncio.wait_for(
                self._ensure_models(), timeout=self._settings.ai_ml_inference_timeout_seconds
            )
            horizon, bastion = await asyncio.wait_for(
                asyncio.to_thread(self._infer_models, text),
                timeout=self._settings.ai_ml_inference_timeout_seconds,
            )
            horizon_attack, horizon_score, horizon_version = horizon
            bastion_attack, bastion_score, bastion_version = bastion
            decision = decide(
                "three_layer_or",
                horizon=NormalizedDetectorOutput(
                    "horizon", horizon_attack, horizon_score, horizon_version
                ),
                bastion=NormalizedDetectorOutput(
                    "bastion", bastion_attack, bastion_score, bastion_version
                ),
                rules=NormalizedDetectorOutput(
                    "rules", False, rules.confidence, rules.model_version
                ),
            )
        except Exception as exc:
            raise RuntimeError("required prompt detector unavailable") from exc

        return EnsembleScreenResult(
            classification=decision.classification,
            reason_code=decision.reason_code,
            rules=rules,
            horizon_attack=horizon_attack,
            horizon_score=horizon_score,
            bastion_attack=bastion_attack,
            bastion_score=bastion_score,
            detector_versions=decision.detector_versions,
            latency_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
        )

    async def readiness(self) -> dict[str, Any]:
        """Return safe readiness metadata without loading model internals."""
        return {
            "rules": "ready",
            "horizon": "ready" if self._horizon is not None else "not_loaded",
            "bastion": "ready" if self._bastion is not None else "not_loaded",
            "required_for_agent_screening": True,
        }

    async def _ensure_models(self) -> None:
        if self._horizon is not None and self._bastion is not None:
            return
        async with self._load_lock:
            if self._horizon is None:
                horizon = await asyncio.to_thread(self._load_horizon)
                self._horizon = horizon
            if self._bastion is None:
                bastion = await asyncio.to_thread(self._load_bastion)
                self._bastion = bastion

    def _load_horizon(self) -> _LoadedHorizon:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            self._settings.ai_ml_horizon_model_id,
            local_files_only=self._settings.ai_ml_local_files_only,
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            self._settings.ai_ml_horizon_model_id,
            local_files_only=self._settings.ai_ml_local_files_only,
        )
        model.eval()
        device = torch.device(self._settings.ai_ml_device)
        model.to(device)
        id2label = {int(key): value.upper() for key, value in model.config.id2label.items()}
        if set(id2label.values()) != {"SAFE", "INJECTION"}:
            raise RuntimeError(f"unexpected Horizon labels: {id2label}")
        injection_id = next(key for key, value in id2label.items() if value == "INJECTION")
        return _LoadedHorizon(
            tokenizer=tokenizer,
            model=model,
            device=device,
            injection_id=injection_id,
            model_version=self._settings.ai_ml_horizon_model_id,
        )

    def _load_bastion(self) -> _LoadedBastion:
        from bastion_prompt_protection import Guard, GuardConfig, Preset

        previous_offline = os.environ.get("HF_HUB_OFFLINE")
        if self._settings.ai_ml_local_files_only:
            os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            guard = Guard(
                config=GuardConfig(
                    preset=Preset.TINY,
                    model=self._settings.ai_ml_bastion_model_id,
                    max_input_chars=self._settings.ai_ml_max_prompt_length,
                )
            )
            if guard._binary is None or not guard._binary._loader.is_available():
                raise RuntimeError("Bastion binary model unavailable")
        finally:
            if self._settings.ai_ml_local_files_only:
                if previous_offline is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = previous_offline
        return _LoadedBastion(guard=guard, model_version=guard.model_version)

    def _infer_models(self, text: str) -> tuple[tuple[bool, float, str], tuple[bool, float, str]]:
        if self._horizon is None or self._bastion is None:
            raise RuntimeError("models are not loaded")
        horizon = self._infer_horizon(text, self._horizon)
        bastion = self._infer_bastion(text, self._bastion)
        return horizon, bastion

    def _infer_horizon(self, text: str, loaded: _LoadedHorizon) -> tuple[bool, float, str]:
        import torch

        inputs = loaded.tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        inputs = {name: value.to(loaded.device) for name, value in inputs.items()}
        with torch.inference_mode():
            probabilities = torch.softmax(loaded.model(**inputs).logits, dim=-1)[0]
        score = float(probabilities[loaded.injection_id].item())
        if not 0.0 <= score <= 1.0:
            raise RuntimeError("invalid Horizon score")
        if self._settings.ai_ml_horizon_classification_method == "threshold":
            predicted_attack = score >= self._settings.ai_ml_horizon_threshold
        else:
            predicted_attack = int(torch.argmax(probabilities).item()) == loaded.injection_id
        return predicted_attack, score, loaded.model_version

    def _infer_bastion(self, text: str, loaded: _LoadedBastion) -> tuple[bool, float, str]:
        output = loaded.guard.protect(text)
        risk = float(output.risk)
        if output.label not in {"safe", "attack"} or not 0.0 <= risk <= 1.0:
            raise RuntimeError("invalid Bastion output")
        return (
            risk >= self._settings.ai_ml_bastion_threshold,
            risk,
            loaded.model_version,
        )
