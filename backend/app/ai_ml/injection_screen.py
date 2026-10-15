"""Deterministic prompt-injection screening baseline.

The screen detects instruction-like content in text that may have come from
an invoice, webpage, email, or other untrusted source. It does not interpret
the text as an executable command and it never makes an authorization
decision.

This intentionally has no model or network dependency. A future classifier
can implement the same contract after a labeled evaluation set exists.
"""

from __future__ import annotations

import re

from app.ai_ml.schemas import InjectionLabel, InjectionScreenResult


class InjectionScreen:
    """Apply conservative, explainable rules to untrusted text."""

    _MAX_TEXT_LENGTH = 20_000

    _HIGH_RISK_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
        (
            "instruction_override",
            re.compile(
                r"\b(?:ignore|disregard|forget|override)\b.{0,80}\b(?:previous|prior|above|system|developer|policy|rule|instruction)s?\b",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        (
            "privileged_role_claim",
            re.compile(
                r"\b(?:system|developer|admin|operator)\s+(?:message|override|instruction|mode)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "secret_exfiltration",
            re.compile(
                r"\b(?:reveal|show|print|send|share|dump|expose)\b.{0,60}\b(?:password|private\s+key|secret|api\s*key|credential(?:s)?|system\s+prompt)\b",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        (
            "obfuscated_instruction_override",
            re.compile(
                r"\bi\s+g\s+n\s+o\s+r\s+e\b.{0,80}\b(?:previous|prior|above|system|developer|policy|rule|instruction)s?\b"
                r"|\bign0re\b.{0,80}\binstructi0ns?\b",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        (
            "multilingual_instruction_override",
            re.compile(
                r"\bignora\b.{0,80}\binstrucciones?\b.{0,80}\b(?:transfiere|env[ií]a|paga|autoriza)\b"
                r"|\bignorer\b.{0,80}\binstructions?\b.{0,80}\b(?:contourner|transf[eé]rer|envoyer|payer|autoriser)\b"
                r"|忽略.{0,30}(?:指示|指令).{0,30}(?:转账|轉帳|发送|付款|批准)"
                r"|(?:前の指示を無視|指示を無視).{0,30}(?:送金|振込|承認なし)",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        (
            "security_control_bypass",
            re.compile(
                r"\b(?:bypass|disable|skip|circumvent)\b.{0,60}\b(?:security|policy|allowlist|approval|limit|verification|guardrail|check)\b",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        (
            "hidden_action_instruction",
            re.compile(
                r"\b(?:hidden|secret|unseen|invisible)\b.{0,60}\b(?:instruction|command|transfer|payment|address)\b",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
    )

    _MEDIUM_RISK_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
        (
            "instructional_marker",
            re.compile(
                r"(?:^|\n|:)\s*(?:system|developer|assistant|instruction|command)\s*:\s*"
                r"|\b(?:system|developer|assistant)\s*:\s*",
                re.IGNORECASE,
            ),
        ),
        (
            "urgent_authorization_request",
            re.compile(
                r"\b(?:urgent|immediately|right\s+now|do\s+not\s+ask|without\s+approval)\b.{0,80}\b(?:send|transfer|pay|approve|authorize)\b",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        (
            "action_redirect",
            re.compile(
                r"\b(?:send|transfer|pay)\b.{0,100}\b(?:instead|new|different|updated)\b.{0,80}\b(?:address|recipient|account)\b",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
    )

    def screen(self, text: str) -> InjectionScreenResult:
        """Return a conservative classification without logging the text.

        Empty, non-string, or oversized input fails closed as suspicious. A
        runtime error in a rule is also represented as malicious so callers
        cannot accidentally treat an unavailable screen as a clean result.
        """
        try:
            if not isinstance(text, str) or not text.strip():
                return InjectionScreenResult(
                    label=InjectionLabel.SUSPICIOUS,
                    confidence=1.0,
                    matched_signals=("invalid_or_empty_input",),
                )

            if len(text) > self._MAX_TEXT_LENGTH:
                return InjectionScreenResult(
                    label=InjectionLabel.SUSPICIOUS,
                    confidence=0.99,
                    matched_signals=("input_too_large",),
                )

            # Preserve line boundaries so role markers such as ``system:``
            # remain detectable while still normalizing horizontal whitespace.
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            normalized = re.sub(r"[^\S\n]+", " ", normalized).strip()
            high_matches = tuple(
                signal for signal, pattern in self._HIGH_RISK_RULES if pattern.search(normalized)
            )
            medium_matches = tuple(
                signal for signal, pattern in self._MEDIUM_RISK_RULES if pattern.search(normalized)
            )
            matches = high_matches + medium_matches

            if high_matches:
                return InjectionScreenResult(
                    label=InjectionLabel.MALICIOUS,
                    confidence=min(0.75 + 0.10 * len(high_matches), 0.99),
                    matched_signals=matches,
                )
            if medium_matches:
                return InjectionScreenResult(
                    label=InjectionLabel.SUSPICIOUS,
                    confidence=min(0.55 + 0.10 * len(medium_matches), 0.85),
                    matched_signals=matches,
                )
            return InjectionScreenResult(
                label=InjectionLabel.BENIGN,
                confidence=0.50,
                matched_signals=(),
            )
        except Exception:
            # The screen is a safety signal. An internal failure must never
            # become an implicit clean result.
            return InjectionScreenResult(
                label=InjectionLabel.MALICIOUS,
                confidence=1.0,
                matched_signals=("screening_error",),
            )
