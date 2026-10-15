"""Focused tests for the policy-independent calldata decoder."""

from __future__ import annotations

from app.services.calldata_decoder import (
    DEFAULT_MAX_CALLDATA_BYTES,
    DEFAULT_MAX_MULTICALL_DEPTH,
    DEFAULT_MAX_MULTICALL_ITEMS,
    SELECTOR_APPROVE,
    SELECTOR_MULTICALL_BYTES,
    SELECTOR_MULTICALL_DEADLINE,
    SELECTOR_SET_APPROVAL_FOR_ALL,
    SELECTOR_TRANSFER,
    DecodeOutcome,
    decode_calldata,
)

TOKEN = "0x" + "1" * 40
RECIPIENT = "0x" + "2" * 40
OPERATOR = "0x" + "3" * 40


def word(value: int | str) -> str:
    if isinstance(value, int):
        return f"{value:064x}"
    return "0" * 24 + value.removeprefix("0x").lower()


def encode_transfer(amount: int = 123) -> str:
    return SELECTOR_TRANSFER + word(RECIPIENT) + word(amount)


def encode_bytes_array(payloads: list[str], *, deadline: int | None = None) -> str:
    encoded_elements = []
    for payload in payloads:
        clean = payload.removeprefix("0x")
        padded = clean + "0" * ((64 - len(clean) % 64) % 64)
        encoded_elements.append(word(len(clean) // 2) + padded)

    count = len(encoded_elements)
    offsets = []
    relative = count * 32
    for element in encoded_elements:
        offsets.append(word(relative))
        relative += len(element) // 2

    array = word(count) + "".join(offsets) + "".join(encoded_elements)
    if deadline is None:
        return SELECTOR_MULTICALL_BYTES + word(32) + array
    return "0x5ae401dc" + word(deadline) + word(64) + array


def test_decodes_erc20_transfer_recipient_and_amount() -> None:
    result = decode_calldata(encode_transfer(456), token_address=TOKEN)

    assert result.outcome is DecodeOutcome.DECODED
    assert result.function_name == "transfer"
    assert result.token_address == TOKEN
    assert result.recipient == RECIPIENT
    assert result.amount == 456


def test_decodes_erc20_approval() -> None:
    calldata = SELECTOR_APPROVE + word(OPERATOR) + word(1000)

    result = decode_calldata(calldata, token_address=TOKEN)

    assert result.outcome is DecodeOutcome.DECODED
    assert result.approval_target == OPERATOR
    assert result.amount == 1000


def test_marks_unlimited_approval_dangerous_without_authorizing() -> None:
    calldata = SELECTOR_APPROVE + word(OPERATOR) + word(2**128)

    result = decode_calldata(calldata, token_address=TOKEN)

    assert result.outcome is DecodeOutcome.DANGEROUS
    assert result.error is not None


def test_marks_set_approval_for_all_as_dangerous_when_enabled() -> None:
    calldata = SELECTOR_SET_APPROVAL_FOR_ALL + word(OPERATOR) + word(1)

    result = decode_calldata(calldata, token_address=TOKEN)

    assert result.outcome is DecodeOutcome.DANGEROUS
    assert result.approval_target == OPERATOR
    assert result.approved is True


def test_decodes_supported_multicall_bytes_array() -> None:
    result = decode_calldata(encode_bytes_array([encode_transfer(7)]), token_address=TOKEN)

    assert result.outcome is DecodeOutcome.DECODED
    assert len(result.nested_actions) == 1
    assert result.nested_actions[0].recipient == RECIPIENT
    assert result.nested_actions[0].amount == 7


def test_decodes_supported_deadline_multicall_bytes_array() -> None:
    result = decode_calldata(
        encode_bytes_array([encode_transfer(8)], deadline=1_700_000_000),
        token_address=TOKEN,
    )

    assert result.selector == SELECTOR_MULTICALL_DEADLINE
    assert result.outcome is DecodeOutcome.DECODED
    assert result.nested_actions[0].amount == 8


def test_marks_dangerous_nested_action_as_non_decodable() -> None:
    dangerous = SELECTOR_SET_APPROVAL_FOR_ALL + word(OPERATOR) + word(1)
    result = decode_calldata(encode_bytes_array([dangerous]), token_address=TOKEN)

    assert result.outcome is DecodeOutcome.DANGEROUS
    assert result.nested_actions[0].outcome is DecodeOutcome.DANGEROUS


def test_rejects_truncated_and_malformed_calldata() -> None:
    assert decode_calldata(SELECTOR_TRANSFER + word(RECIPIENT)).outcome is DecodeOutcome.MALFORMED
    assert decode_calldata("0x123").outcome is DecodeOutcome.MALFORMED
    assert decode_calldata("0x095ea7b3zz").outcome is DecodeOutcome.MALFORMED


def test_rejects_invalid_address_and_unknown_selector() -> None:
    invalid_address = SELECTOR_TRANSFER + word("0x" + "g" * 40) + word(1)
    unknown = decode_calldata("0xdeadbeef" + word(1))

    assert decode_calldata(invalid_address).outcome is DecodeOutcome.MALFORMED
    assert unknown.outcome is DecodeOutcome.UNSUPPORTED


def test_empty_calldata_remains_valid_native_eth_input() -> None:
    result = decode_calldata("")

    assert result.outcome is DecodeOutcome.EMPTY
    assert result.function_name == "empty"


def test_rejects_calldata_above_configured_size_limit() -> None:
    calldata = encode_transfer()

    result = decode_calldata(calldata, max_calldata_bytes=len(calldata) - 1)

    assert result.outcome is DecodeOutcome.LIMIT_EXCEEDED
    assert "size" in (result.error or "")


def test_accepts_calldata_at_size_limit() -> None:
    calldata = encode_transfer()

    result = decode_calldata(calldata, max_calldata_bytes=len(calldata))

    assert result.outcome is DecodeOutcome.DECODED


def test_rejects_multicall_above_item_limit_before_decoding_items() -> None:
    calldata = encode_bytes_array([encode_transfer(1), encode_transfer(2)])

    result = decode_calldata(calldata, max_multicall_items=1)

    assert result.outcome is DecodeOutcome.LIMIT_EXCEEDED
    assert "item count" in (result.error or "")


def test_accepts_multicall_at_item_limit() -> None:
    calldata = encode_bytes_array([encode_transfer(1), encode_transfer(2)])

    result = decode_calldata(calldata, max_multicall_items=2)

    assert result.outcome is DecodeOutcome.DECODED
    assert len(result.nested_actions) == 2


def test_rejects_nested_multicall_above_depth_limit() -> None:
    nested_once = encode_bytes_array([encode_transfer(1)])
    nested_twice = encode_bytes_array([nested_once])
    nested_thrice = encode_bytes_array([nested_twice])

    result = decode_calldata(nested_thrice, max_multicall_depth=1)

    assert result.outcome is DecodeOutcome.LIMIT_EXCEEDED
    assert result.nested_actions[0].outcome is DecodeOutcome.LIMIT_EXCEEDED


def test_accepts_nested_multicall_at_depth_limit() -> None:
    nested_once = encode_bytes_array([encode_transfer(1)])
    nested_twice = encode_bytes_array([nested_once])

    result = decode_calldata(nested_twice, max_multicall_depth=2)

    assert result.outcome is DecodeOutcome.DECODED


def test_default_limits_are_explicit_and_nonzero() -> None:
    assert DEFAULT_MAX_CALLDATA_BYTES > 0
    assert DEFAULT_MAX_MULTICALL_ITEMS > 0
    assert DEFAULT_MAX_MULTICALL_DEPTH > 0
