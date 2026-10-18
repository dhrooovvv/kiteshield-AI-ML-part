"""Exact, bounded ETH/wei conversions. No binary floating point."""

import re

from app.exceptions import ValidationError


def eth_to_wei(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"(?:\d+|\d*\.\d{1,18})", value):
        raise ValidationError("Use one positive decimal ETH amount with at most 18 decimal places")
    whole, _, fraction = value.partition(".")
    amount = int(whole or "0") * 10**18 + int(fraction.ljust(18, "0") or "0")
    if not 0 < amount <= 10**24:
        raise ValidationError("Amount must be positive and within the supported limit")
    return str(amount)


def wei_to_eth(value: str | int) -> str:
    whole, fraction = divmod(int(value), 10**18)
    return f"{whole}.{fraction:018d}".rstrip("0").rstrip(".")
