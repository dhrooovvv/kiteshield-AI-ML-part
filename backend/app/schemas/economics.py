"""Isolated advisory schemas; existing transaction schemas are unchanged."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EconomicCheckRequest(BaseModel):
    """Caller-supplied gas estimates in Gwei; not a network fee quote."""

    model_config = ConfigDict(extra="forbid")

    value_wei: str = Field(default="0", min_length=1, max_length=78, pattern=r"^[0-9]+$")
    estimated_gas: int = Field(default=21000, strict=True, ge=1, le=30_000_000)
    gas_price_gwei: Decimal = Field(
        default=Decimal("20"), ge=0, le=Decimal("1000000000"), decimal_places=9
    )
    max_gas_price_gwei: Decimal = Field(
        default=Decimal("100"), ge=0, le=Decimal("1000000000"), decimal_places=9
    )

    @field_validator("value_wei")
    @classmethod
    def validate_value_wei(cls, value: str) -> str:
        if int(value) > 2**256 - 1:
            raise ValueError("value_wei exceeds uint256")
        return str(int(value))


class EconomicCheckResponse(BaseModel):
    """All monetary amounts are decimal strings to avoid JSON float loss."""

    advisory_only: Literal[True] = True
    estimate_source: Literal["CALLER_SUPPLIED"] = "CALLER_SUPPLIED"
    is_economically_viable: bool
    gas_cost_wei: str
    gas_cost_eth: str
    gas_to_value_ratio: str | None
    warnings: list[str]
    estimated_gas: int
    gas_price_gwei: str
    max_gas_price_gwei: str
    value_wei: str
