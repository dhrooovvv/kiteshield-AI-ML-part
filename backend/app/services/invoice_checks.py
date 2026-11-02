"""Pure deterministic eligibility checks. Model output has no financial authority."""

import hashlib
import re
import unicodedata
from datetime import date

from app.ai_ml.injection_screen import InjectionScreen
from app.services.amounts import eth_to_wei

ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
AMOUNT = r"[-+]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?"
ETH_AMOUNTS = re.compile(rf"(?<![\w.])({AMOUNT})\s*ETH\b|\bETH\s*({AMOUNT})(?![\w.])", re.I)
LAYERS = ("extraction_validator", "registry", "screening", "policy")


def canonical_text(text):
    return "".join(
        c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Cf"
    )


def invoice_keys(vendor_id, number, amount):
    identity = f"{vendor_id}:{number.upper()}"
    return (
        hashlib.sha256(f"{identity}:{amount}".encode()).hexdigest(),
        hashlib.sha256(identity.encode()).hexdigest(),
    )


def document_checks(
    text, fields, vendors, *, today=None, overdue=30, future=90, rules_enabled=True
):
    """Returns all observable failures, not just the first, for offline ablations."""
    today = today or date.today()
    failures = []
    normalized = canonical_text(text)
    if fields is None:
        failures.append(("extraction_validator", "EXTRACTION_INVALID"))
    else:
        due = date.fromisoformat(fields.due_date)
        delta = (due - today).days
        if delta < -overdue or delta > future:
            failures.append(("extraction_validator", "DUE_DATE_OUT_OF_RANGE"))
        elif delta > 0:
            failures.append(("extraction_validator", "NOT_DUE_YET"))
        if fields.invoice_number not in text:
            failures.append(("extraction_validator", "INVOICE_NUMBER_NOT_IN_DOCUMENT"))
        if fields.due_date not in text:
            failures.append(("extraction_validator", "DUE_DATE_NOT_IN_DOCUMENT"))
        amount_values = set()
        try:
            for match in ETH_AMOUNTS.finditer(normalized):
                amount_values.add(eth_to_wei(match[1] or match[2]))
        except Exception:
            failures.append(("extraction_validator", "INVALID_DOCUMENT_AMOUNT"))
        if amount_values != {eth_to_wei(fields.amount_eth)}:
            failures.append(("extraction_validator", "MISSING_OR_CONFLICTING_AMOUNT"))
    if any(unicodedata.category(c) == "Cf" for c in text):
        failures.append(("extraction_validator", "INVISIBLE_TEXT_REQUIRES_REVIEW"))
    exact = [v for v in vendors if fields and v.active and v.name == fields.vendor_name]
    vendor = exact[0] if len(exact) == 1 else None
    mentioned = [v for v in vendors if v.active and v.name in text]
    if vendor is None:
        failures.append(("registry", "EXACT_VENDOR_REQUIRED"))
    elif len(mentioned) != 1 or mentioned[0].id != vendor.id:
        failures.append(("registry", "AMBIGUOUS_VENDOR_IN_DOCUMENT"))
    if vendor:
        addresses = ADDRESS.findall(normalized)
        if any(a.lower() != vendor.payout_address.lower() for a in addresses):
            failures.append(("registry", "DOCUMENT_ADDRESS_MISMATCH"))
        if int(eth_to_wei(fields.amount_eth)) > int(vendor.maximum_wei):
            failures.append(("registry", "VENDOR_INVOICE_MAXIMUM"))
    if rules_enabled:
        screened = InjectionScreen().screen(normalized)
        if screened.label.value != "BENIGN":
            failures.append(("screening", "RULES_" + screened.label.value))
    return vendor, failures


def decision_summary(failures):
    ordered = sorted(failures, key=lambda x: LAYERS.index(x[0]))
    return {
        "first_stop": ordered[0][0] if ordered else None,
        "reasons": [{"layer": a, "code": b} for a, b in ordered],
        "without_layer": {
            layer: {
                "would_pass_checks": (
                    None
                    if any(b in ("EXTRACTION_INVALID", "EXACT_VENDOR_REQUIRED") for _, b in ordered)
                    else not any(a != layer for a, _ in ordered)
                ),
                "remaining_reasons": [b for a, b in ordered if a != layer],
            }
            for layer in LAYERS
        },
        "counterfactual_scope": "Offline check replay, not payment authorization",
    }
