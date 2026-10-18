"""Boundary tests adapted from China's gas-economics checks."""

import pytest

from app.services.economic_guard import evaluate_gas_economics


def assess(value=1000, gas=10, price=20, ceiling=100):
    return evaluate_gas_economics(
        value_wei=value,
        estimated_gas=gas,
        gas_price_wei=price,
        max_gas_price_wei=ceiling,
    )


def test_routine_fee_is_exact_and_advisory():
    result = assess()
    assert result.is_economically_viable
    assert result.gas_cost_wei == "200"
    assert result.gas_cost_eth == "0.0000000000000002"
    assert result.gas_to_value_ratio == "0.2000"
    assert result.warnings == ()


@pytest.mark.parametrize(
    ("value", "price", "viable", "warnings"),
    [
        (1000, 100, True, ("HIGH_GAS_TO_VALUE_RATIO",)),
        (1000, 101, False, ("GAS_PRICE_ABOVE_CEILING", "GAS_FEE_EXCEEDS_TRANSFER_VALUE")),
        (199, 20, False, ("GAS_FEE_EXCEEDS_TRANSFER_VALUE",)),
        (200, 20, True, ("HIGH_GAS_TO_VALUE_RATIO",)),
        (399, 20, True, ("HIGH_GAS_TO_VALUE_RATIO",)),
        (400, 20, True, ()),
        (401, 20, True, ()),
        (0, 20, True, ("ZERO_VALUE_RATIO_UNAVAILABLE",)),
    ],
)
def test_reference_warning_boundaries(value, price, viable, warnings):
    result = assess(value=value, price=price)
    assert result.is_economically_viable is viable
    assert result.warnings == warnings
    if value == 0:
        assert result.gas_to_value_ratio is None


def test_integer_math_retains_wei_beyond_float_precision():
    result = assess(value=2**256 - 1, gas=30_000_000, price=999_999_999_999_999_999)
    assert result.gas_cost_wei == str(30_000_000 * 999_999_999_999_999_999)


def test_explicit_zero_ceiling_is_not_replaced_with_default():
    result = assess(price=1, ceiling=0)
    assert not result.is_economically_viable
    assert "GAS_PRICE_ABOVE_CEILING" in result.warnings


@pytest.mark.parametrize(
    ("field", "value"),
    [("value", -1), ("gas", 0), ("price", -1), ("ceiling", -1), ("value", True)],
)
def test_invalid_service_inputs_are_rejected(field, value):
    with pytest.raises(ValueError):
        assess(**{field: value})
