"""Advisory gas economics adapted from China-main's EconomicGuard.

Reference: China-main (1).zip, backend/services/economic_guard.py.
Preserves its gas-price ceiling, fee/value, and >50% warning checks. Unlike
the reference, calculations use integer wei and Decimal, never float money.
No RPC, persistence, policy, authorization, or execution is performed here.
DEX parsing is deliberately excluded until separately reviewed against ABI.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext


@dataclass(frozen=True)
class GasEconomics:
    """Fee advice, not permission to execute a transaction."""

    is_economically_viable: bool
    gas_cost_wei: str
    gas_cost_eth: str
    gas_to_value_ratio: str | None
    warnings: tuple[str, ...]


def evaluate_gas_economics(
    *,
    value_wei: int,
    estimated_gas: int,
    gas_price_wei: int,
    max_gas_price_wei: int,
) -> GasEconomics:
    """Calculate caller-supplied estimates; no live network estimate is made.

    A zero-value call has no meaningful fee/value ratio. It is not itself an
    uneconomic transfer, but still receives a warning and the gas-price check.
    """
    values = (value_wei, estimated_gas, gas_price_wei, max_gas_price_wei)
    if any(type(value) is not int or value < 0 for value in values) or estimated_gas == 0:
        raise ValueError("Gas economics requires non-negative integers and positive gas units")

    gas_cost = estimated_gas * gas_price_wei
    warnings: list[str] = []
    viable = True
    if gas_price_wei > max_gas_price_wei:
        warnings.append("GAS_PRICE_ABOVE_CEILING")
        viable = False
    if value_wei == 0:
        warnings.append("ZERO_VALUE_RATIO_UNAVAILABLE")
    elif gas_cost > value_wei:
        warnings.append("GAS_FEE_EXCEEDS_TRANSFER_VALUE")
        viable = False
    elif gas_cost * 2 > value_wei:
        warnings.append("HIGH_GAS_TO_VALUE_RATIO")

    with localcontext() as context:
        context.prec = 100
        eth = format(Decimal(gas_cost) / Decimal(10**18), "f")
        ratio = (
            format((Decimal(gas_cost) / Decimal(value_wei)).quantize(Decimal("0.0001")), "f")
            if value_wei
            else None
        )
    return GasEconomics(viable, str(gas_cost), eth, ratio, tuple(warnings))
