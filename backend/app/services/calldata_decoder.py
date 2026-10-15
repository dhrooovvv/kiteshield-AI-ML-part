"""Strict, policy-independent decoding of supported EVM calldata.

The decoder produces facts for a later policy layer.  It never authorizes,
blocks, escalates, or signs a transaction.  Anything that cannot be decoded
unambiguously is returned as a non-decodable outcome so callers cannot mistake
parser failure for a safe action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

SELECTOR_APPROVE = "0x095ea7b3"
SELECTOR_SET_APPROVAL_FOR_ALL = "0xa22cb465"
SELECTOR_TRANSFER = "0xa9059cbb"
SELECTOR_TRANSFER_FROM = "0x23b872dd"
SELECTOR_MULTICALL_BYTES = "0xac9650d8"  # multicall(bytes[])
SELECTOR_MULTICALL_DEADLINE = "0x5ae401dc"  # multicall(uint256,bytes[])

MAX_ALLOWED_APPROVAL_AMOUNT = 2**128
DEFAULT_MAX_CALLDATA_BYTES = 128 * 1024
DEFAULT_MAX_MULTICALL_ITEMS = 128
DEFAULT_MAX_MULTICALL_DEPTH = 4
_WORD_HEX_LENGTH = 64
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class DecodeOutcome(StrEnum):
    """Structural result of parsing calldata, not an authorization verdict."""

    EMPTY = "empty"
    DECODED = "decoded"
    MALFORMED = "malformed"
    UNSUPPORTED = "unsupported"
    DANGEROUS = "dangerous"
    AMBIGUOUS = "ambiguous"
    LIMIT_EXCEEDED = "limit_exceeded"


@dataclass(frozen=True)
class DecodedAction:
    """Normalized facts extracted from one supported calldata action."""

    selector: str
    function_name: str
    outcome: DecodeOutcome
    token_address: str | None = None
    recipient: str | None = None
    amount: int | None = None
    approval_target: str | None = None
    approved: bool | None = None
    nested_actions: tuple[DecodedAction, ...] = ()
    error: str | None = None


def _invalid(
    selector: str,
    outcome: DecodeOutcome,
    error: str,
    *,
    function_name: str = "unknown",
    token_address: str | None = None,
) -> DecodedAction:
    return DecodedAction(
        selector=selector,
        function_name=function_name,
        outcome=outcome,
        token_address=token_address,
        error=error,
    )


class _LimitExceededError(ValueError):
    """Internal parse error used to preserve limit-specific outcomes."""


def _validate_address(address: str | None, field_name: str) -> str | None:
    if address is None:
        return None
    if not _ADDRESS_RE.fullmatch(address):
        raise ValueError(f"invalid {field_name} address")
    return address.lower()


def _word(data: str, index: int) -> str:
    start = index * _WORD_HEX_LENGTH
    end = start + _WORD_HEX_LENGTH
    if end > len(data):
        raise ValueError(f"missing ABI word at index {index}")
    return data[start:end]


def _address_from_word(value: str, field_name: str) -> str:
    if len(value) != _WORD_HEX_LENGTH or value[:24] != "0" * 24:
        raise ValueError(f"invalid ABI address word for {field_name}")
    address = "0x" + value[24:]
    validated = _validate_address(address, field_name)
    assert validated is not None
    return validated


def _uint_from_word(value: str, field_name: str) -> int:
    if len(value) != _WORD_HEX_LENGTH:
        raise ValueError(f"invalid ABI uint word for {field_name}")
    return int(value, 16)


def _bool_from_word(value: str, field_name: str) -> bool:
    parsed = _uint_from_word(value, field_name)
    if parsed not in (0, 1):
        raise ValueError(f"invalid ABI bool value for {field_name}")
    return bool(parsed)


def _require_exact_words(data: str, count: int) -> None:
    expected = count * _WORD_HEX_LENGTH
    if len(data) != expected:
        raise ValueError(f"expected exactly {count} ABI words")


def _decode_static(
    calldata: str,
    *,
    token_address: str | None,
) -> DecodedAction:
    has_prefix = calldata.startswith("0x")
    selector = calldata[:10] if has_prefix else "0x" + calldata[:8]
    data = calldata[10:] if has_prefix else calldata[8:]
    selector = selector.lower()
    normalized_token = _validate_address(token_address, "token")

    try:
        if selector == SELECTOR_TRANSFER:
            _require_exact_words(data, 2)
            return DecodedAction(
                selector=selector,
                function_name="transfer",
                outcome=DecodeOutcome.DECODED,
                token_address=normalized_token,
                recipient=_address_from_word(_word(data, 0), "recipient"),
                amount=_uint_from_word(_word(data, 1), "amount"),
            )

        if selector == SELECTOR_TRANSFER_FROM:
            _require_exact_words(data, 3)
            return DecodedAction(
                selector=selector,
                function_name="transferFrom",
                outcome=DecodeOutcome.DECODED,
                token_address=normalized_token,
                recipient=_address_from_word(_word(data, 1), "recipient"),
                amount=_uint_from_word(_word(data, 2), "amount"),
            )

        if selector == SELECTOR_APPROVE:
            _require_exact_words(data, 2)
            amount = _uint_from_word(_word(data, 1), "amount")
            outcome = (
                DecodeOutcome.DANGEROUS
                if amount >= MAX_ALLOWED_APPROVAL_AMOUNT
                else DecodeOutcome.DECODED
            )
            return DecodedAction(
                selector=selector,
                function_name="approve",
                outcome=outcome,
                token_address=normalized_token,
                approval_target=_address_from_word(_word(data, 0), "approval target"),
                amount=amount,
                error=(
                    "unlimited or excessive approval"
                    if outcome is DecodeOutcome.DANGEROUS
                    else None
                ),
            )

        if selector == SELECTOR_SET_APPROVAL_FOR_ALL:
            _require_exact_words(data, 2)
            approved = _bool_from_word(_word(data, 1), "approved")
            outcome = DecodeOutcome.DANGEROUS if approved else DecodeOutcome.DECODED
            return DecodedAction(
                selector=selector,
                function_name="setApprovalForAll",
                outcome=outcome,
                token_address=normalized_token,
                approval_target=_address_from_word(_word(data, 0), "operator"),
                approved=approved,
                error=("blanket operator approval" if approved else None),
            )

        return _invalid(selector, DecodeOutcome.UNSUPPORTED, "unsupported selector")
    except (ValueError, OverflowError) as exc:
        return _invalid(
            selector,
            DecodeOutcome.MALFORMED,
            str(exc),
            function_name={
                SELECTOR_TRANSFER: "transfer",
                SELECTOR_TRANSFER_FROM: "transferFrom",
                SELECTOR_APPROVE: "approve",
                SELECTOR_SET_APPROVAL_FOR_ALL: "setApprovalForAll",
            }.get(selector, "unknown"),
            token_address=normalized_token,
        )


def _read_multicall_bytes(
    data: str,
    selector: str,
    *,
    max_items: int,
) -> tuple[str, list[str]]:
    """Decode the canonical ABI head and bytes[] payload for supported calls."""
    if selector == SELECTOR_MULTICALL_BYTES:
        _require_exact_words(data[: _WORD_HEX_LENGTH * 1], 1)
        offset = _uint_from_word(_word(data, 0), "bytes[] offset")
        head_words = 1
    else:
        _require_exact_words(data[: _WORD_HEX_LENGTH * 2], 2)
        offset = _uint_from_word(_word(data, 1), "bytes[] offset")
        head_words = 2

    if offset % 32 or offset < head_words * 32 or offset + 32 > len(data) // 2:
        raise ValueError("invalid bytes[] offset")

    array_start = offset * 2
    count = _uint_from_word(data[array_start : array_start + 64], "bytes[] length")
    if count > max_items:
        raise _LimitExceededError(
            f"multicall item count {count} exceeds limit {max_items}"
        )
    offsets_start = array_start + 64
    offsets_end = offsets_start + count * 64
    if offsets_end > len(data):
        raise ValueError("truncated bytes[] offsets")

    elements: list[str] = []
    ranges: list[tuple[int, int]] = []
    element_base = array_start + 64
    for index in range(count):
        relative = _uint_from_word(
            data[offsets_start + index * 64 : offsets_start + (index + 1) * 64],
            f"bytes[] element {index} offset",
        )
        element_start = element_base + relative * 2
        if relative % 32 or element_start < offsets_end or element_start + 64 > len(data):
            raise ValueError(f"invalid bytes[] element {index} offset")
        byte_length = _uint_from_word(data[element_start : element_start + 64], "bytes length")
        payload_start = element_start + 64
        payload_end = payload_start + ((byte_length + 31) // 32) * 64
        if payload_end > len(data):
            raise ValueError(f"truncated bytes[] element {index}")
        payload = data[payload_start : payload_start + byte_length * 2]
        if len(payload) < 8:
            raise ValueError(f"nested element {index} has no complete selector")
        elements.append(payload)
        ranges.append((element_start, payload_end))

    previous_end = offsets_end
    for element_start, payload_end in sorted(ranges):
        if element_start < previous_end:
            raise ValueError("overlapping bytes[] elements")
        previous_end = payload_end
    if previous_end != len(data):
        raise ValueError("trailing bytes after bytes[] payload")

    return selector, elements


def _decode_multicall(
    calldata: str,
    *,
    token_address: str | None,
    max_multicall_items: int,
    max_multicall_depth: int,
    depth: int,
) -> DecodedAction:
    selector = calldata[:10].lower()
    data = calldata[10:]
    normalized_token = _validate_address(token_address, "token")
    if depth > max_multicall_depth:
        return _invalid(
            selector,
            DecodeOutcome.LIMIT_EXCEEDED,
            f"multicall nesting depth {depth} exceeds limit {max_multicall_depth}",
            function_name="multicall",
            token_address=normalized_token,
        )
    try:
        _, nested_payloads = _read_multicall_bytes(
            data,
            selector,
            max_items=max_multicall_items,
        )
        nested = tuple(
            _decode_static(payload, token_address=normalized_token)
            if payload[:8] not in {SELECTOR_MULTICALL_BYTES[2:], SELECTOR_MULTICALL_DEADLINE[2:]}
            else _decode_multicall(
                "0x" + payload,
                token_address=normalized_token,
                max_multicall_items=max_multicall_items,
                max_multicall_depth=max_multicall_depth,
                depth=depth + 1,
            )
            for payload in nested_payloads
        )
    except _LimitExceededError as exc:
        return _invalid(
            selector,
            DecodeOutcome.LIMIT_EXCEEDED,
            str(exc),
            function_name="multicall",
            token_address=normalized_token,
        )
    except (ValueError, OverflowError) as exc:
        return _invalid(
            selector,
            DecodeOutcome.MALFORMED,
            str(exc),
            function_name="multicall",
            token_address=normalized_token,
        )

    if any(action.outcome is DecodeOutcome.LIMIT_EXCEEDED for action in nested):
        return DecodedAction(
            selector=selector,
            function_name="multicall",
            outcome=DecodeOutcome.LIMIT_EXCEEDED,
            token_address=normalized_token,
            nested_actions=nested,
            error="nested multicall exceeded a configured limit",
        )
    if any(action.outcome is not DecodeOutcome.DECODED for action in nested):
        return DecodedAction(
            selector=selector,
            function_name="multicall",
            outcome=DecodeOutcome.DANGEROUS,
            token_address=normalized_token,
            nested_actions=nested,
            error="nested action is unsupported, malformed, or dangerous",
        )
    return DecodedAction(
        selector=selector,
        function_name="multicall",
        outcome=DecodeOutcome.DECODED,
        token_address=normalized_token,
        nested_actions=nested,
    )


def decode_calldata(
    calldata: str,
    *,
    token_address: str | None = None,
    max_calldata_bytes: int = DEFAULT_MAX_CALLDATA_BYTES,
    max_multicall_items: int = DEFAULT_MAX_MULTICALL_ITEMS,
    max_multicall_depth: int = DEFAULT_MAX_MULTICALL_DEPTH,
) -> DecodedAction:
    """Decode supported calldata into normalized facts.

    Empty calldata is valid for a native ETH transaction and returns ``EMPTY``.
    Limits apply to non-empty calldata and must be positive or zero as
    appropriate: calldata bytes, multicall items, and nested depth.
    All unsupported, invalid, or limit-exceeding input returns a non-decodable
    outcome.
    """
    if not isinstance(calldata, str):
        return _invalid("", DecodeOutcome.MALFORMED, "calldata must be a string")
    if calldata in ("", "0x"):
        try:
            normalized_token = _validate_address(token_address, "token")
        except ValueError as exc:
            return _invalid("", DecodeOutcome.MALFORMED, str(exc))
        return DecodedAction("", "empty", DecodeOutcome.EMPTY, token_address=normalized_token)
    if max_calldata_bytes < 0 or max_multicall_items < 0 or max_multicall_depth < 0:
        return _invalid("", DecodeOutcome.MALFORMED, "decoder limits must not be negative")
    calldata_bytes = len(calldata.encode("utf-8"))
    if calldata_bytes > max_calldata_bytes:
        return _invalid(
            "",
            DecodeOutcome.LIMIT_EXCEEDED,
            f"calldata size {calldata_bytes} exceeds limit {max_calldata_bytes} bytes",
        )
    if not calldata.startswith("0x"):
        return _invalid("", DecodeOutcome.MALFORMED, "calldata must be 0x-prefixed")

    clean = calldata[2:]
    if len(clean) < 8 or len(clean) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", clean):
        return _invalid("0x" + clean[:8].lower(), DecodeOutcome.MALFORMED, "invalid calldata hex")

    selector = "0x" + clean[:8].lower()
    if selector in {SELECTOR_MULTICALL_BYTES, SELECTOR_MULTICALL_DEADLINE}:
        try:
            return _decode_multicall(
                "0x" + clean,
                token_address=token_address,
                max_multicall_items=max_multicall_items,
                max_multicall_depth=max_multicall_depth,
                depth=0,
            )
        except _LimitExceededError as exc:
            return _invalid(
                selector,
                DecodeOutcome.LIMIT_EXCEEDED,
                str(exc),
                function_name="multicall",
            )
        except ValueError as exc:
            return _invalid(selector, DecodeOutcome.MALFORMED, str(exc), function_name="multicall")
    try:
        return _decode_static("0x" + clean, token_address=token_address)
    except ValueError as exc:
        return _invalid(selector, DecodeOutcome.MALFORMED, str(exc))
