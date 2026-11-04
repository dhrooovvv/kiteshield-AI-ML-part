"""Invoice-only use of the existing Horizon/Bastion weights, without financial authority."""

import asyncio
import hashlib
import html
import json
import math
import threading
import time

from app.ai_ml.ensemble_screen import PromptInjectionEnsemble
from app.ai_ml.experimental_decision_policy import NormalizedDetectorOutput, decide
from app.ai_ml.injection_screen import InjectionScreen
from app.core.config import get_settings
from app.services.invoice_checks import canonical_text

VERSION = "invoice-horizon-bastion-windows-v1"


def enabled():
    settings = get_settings()
    return settings.invoice_learned_screening_enabled or settings.learned_screening_enabled


def profile():
    s = get_settings()
    parameters = {
        "version": VERSION,
        "horizon": s.ai_ml_horizon_model_id,
        "bastion": s.ai_ml_bastion_model_id,
        "horizon_method": s.ai_ml_horizon_classification_method,
        "horizon_threshold": s.ai_ml_horizon_threshold,
        "bastion_threshold": s.ai_ml_bastion_threshold,
        "max_characters": s.ai_ml_max_prompt_length,
        "timeout": s.ai_ml_inference_timeout_seconds,
        "local_only": s.ai_ml_local_files_only,
        "device": s.ai_ml_device,
    }
    return hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()


def document_digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def windows(text, fits, max_characters):
    """Every character is inspected; adaptive splits prevent model truncation."""
    if max_characters <= 0:
        raise ValueError("Positive window size required")
    start = 0
    while start < len(text):
        end = min(len(text), start + min(1500, max_characters))
        while not fits(text[start:end]):
            if end - start <= 1:
                raise ValueError("Detector cannot represent this input")
            end = start + (end - start) // 2
        yield text[start:end]
        if end == len(text):
            break
        start = end - min(128, (end - start) // 4)


class InvoiceScreeningService:
    def __init__(self):
        self._ensemble = None
        self._lock = asyncio.Lock()
        # Worker threads retain this lock even when an awaiting request times out.
        self._worker_lock = threading.Lock()

    def _service(self):
        if self._ensemble is None:
            self._ensemble = PromptInjectionEnsemble(settings=get_settings())
        return self._ensemble

    async def screen(self, document):
        started = time.monotonic()
        proof = {
            "profile": profile(),
            "document_sha256": document_digest(document),
            "horizon": {"status": "not_run"},
            "bastion": {"status": "not_run"},
        }
        try:
            async with asyncio.timeout(get_settings().ai_ml_inference_timeout_seconds):
                async with self._lock:
                    if not document.strip() or len(document) > 20000:
                        raise ValueError("Invalid invoice length")
                    text = canonical_text(html.unescape(document))
                    rules = InjectionScreen().screen(text)
                    proof["rules"] = {
                        "label": rules.label.value,
                        "signals": list(rules.matched_signals),
                    }
                    if rules.label.value != "BENIGN":
                        return {
                            **proof,
                            "classification": "ATTACK",
                            "reason": "RULES_POSITIVE",
                            "latency_ms": round((time.monotonic() - started) * 1000),
                        }
                    service = self._service()
                    await service._ensure_models()
                    deadline = started + get_settings().ai_ml_inference_timeout_seconds
                    measured = await asyncio.to_thread(self._infer, text, deadline)
                    return {
                        **proof,
                        **measured,
                        "latency_ms": round((time.monotonic() - started) * 1000),
                    }
        except asyncio.CancelledError:
            raise
        except Exception:
            return {
                **proof,
                "classification": "ERROR",
                "reason": "DETECTOR_UNAVAILABLE",
                "latency_ms": round((time.monotonic() - started) * 1000),
            }

    def _infer(self, text, deadline):
        from tokenizers import Tokenizer

        with self._worker_lock:
            service = self._service()
            horizon, bastion = service._horizon, service._bastion
            if horizon is None or bastion is None or bastion.guard._binary is None:
                raise RuntimeError("Both model detectors are required")
            binary = bastion.guard._binary
            if not binary.is_available():
                raise RuntimeError("Bastion binary unavailable")
            tokenizer = Tokenizer.from_str(binary._loader.artifact.tokenizer.to_str())
            tokenizer.no_truncation()
            tokenizer.no_padding()
            truncation = binary._loader.artifact.tokenizer.truncation
            bastion_limit = min(512, truncation["max_length"] if truncation else 512)

            def fits(chunk):
                return (
                    len(horizon.tokenizer.encode(chunk, truncation=False)) <= 512
                    and len(tokenizer.encode(chunk).ids) <= bastion_limit
                )

            h_attack, b_attack, h_score, b_score, count = False, False, 0.0, 0.0, 0
            for chunk in windows(text, fits, get_settings().ai_ml_max_prompt_length):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Invoice detector deadline exceeded")
                hp, hs, _ = service._infer_horizon(chunk, horizon)
                # Require real binary inference, never the SDK's heuristic-only fallback.
                bp = binary.predict(chunk)
                if not bp.available or not math.isfinite(bp.risk) or not 0 <= bp.risk <= 1:
                    raise RuntimeError("Bastion binary output unavailable")
                h_attack |= hp
                b_attack |= bp.risk >= get_settings().ai_ml_bastion_threshold
                h_score, b_score = max(h_score, hs), max(b_score, bp.risk)
                count += 1
            if count == 0 or time.monotonic() >= deadline:
                raise TimeoutError("Incomplete invoice coverage")
            h_version = getattr(horizon.model.config, "_commit_hash", None) or horizon.model_version
            b_version = binary._loader.revision or bastion.model_version
            decision = decide(
                "three_layer_or",
                horizon=NormalizedDetectorOutput("horizon", h_attack, h_score, h_version),
                bastion=NormalizedDetectorOutput("bastion", b_attack, b_score, b_version),
                rules=NormalizedDetectorOutput("rules", False),
            )
            return {
                "classification": decision.classification.value,
                "reason": decision.reason_code,
                "windows": count,
                "complete": True,
                "horizon": {
                    "status": "ready",
                    "attack": h_attack,
                    "score": h_score,
                    "version": h_version,
                },
                "bastion": {
                    "status": "ready",
                    "attack": b_attack,
                    "score": b_score,
                    "version": b_version,
                },
            }


invoice_screening = InvoiceScreeningService()


def valid_clearance(proof, text):
    """Revalidate the server's stored evidence, never a caller's BENIGN claim."""
    try:
        return (
            proof["classification"] == "BENIGN"
            and proof["complete"] is True
            and proof["profile"] == profile()
            and proof["document_sha256"] == document_digest(text)
            and type(proof["windows"]) is int
            and proof["windows"] > 0
            and all(
                proof[name]["status"] == "ready"
                and proof[name]["attack"] is False
                and bool(proof[name]["version"])
                and math.isfinite(proof[name]["score"])
                and 0 <= proof[name]["score"] <= 1
                for name in ("horizon", "bastion")
            )
            and proof["bastion"]["score"] < get_settings().ai_ml_bastion_threshold
            and (
                proof["horizon"]["score"] < get_settings().ai_ml_horizon_threshold
                if get_settings().ai_ml_horizon_classification_method == "threshold"
                else proof["horizon"]["score"] <= 0.5
            )
        )
    except (KeyError, TypeError, ValueError):
        return False
