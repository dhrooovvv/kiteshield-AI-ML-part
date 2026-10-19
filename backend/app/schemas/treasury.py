"""Explicit mandate and activation inputs; never accept floating-point money."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from web3 import Web3


class MandateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=0)
    sender: str
    recipient: str
    chain_id: Literal[11155111] = 11155111
    target_balance_wei: str
    sweep_maximum_wei: str
    minimum_excess_wei: str
    cooldown_seconds: int = Field(default=600, ge=60, le=86400)
    daily_action_limit: int = Field(default=3, ge=1, le=100)
    freshness_seconds: int = Field(default=60, ge=15, le=300)

    @field_validator("sender", "recipient")
    @classmethod
    def address(cls, value: str) -> str:
        if not Web3.is_address(value) or int(value, 16) == 0:
            raise ValueError("A nonzero public Ethereum address is required")
        return Web3.to_checksum_address(value)

    @field_validator("target_balance_wei", "sweep_maximum_wei", "minimum_excess_wei")
    @classmethod
    def exact_amount(cls, value: str) -> str:
        if not value.isascii() or not value.isdigit() or len(value) > 78:
            raise ValueError("Use an unsigned integer wei string")
        if int(value) > 2**256 - 1:
            raise ValueError("Amount exceeds uint256")
        return str(int(value))

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.sender.lower() == self.recipient.lower():
            raise ValueError("Sweep recipient must differ from sender")
        if int(self.sweep_maximum_wei) <= 0 or int(self.minimum_excess_wei) <= 0:
            raise ValueError("Sweep maximum and minimum excess must be positive")
        if int(self.minimum_excess_wei) > int(self.sweep_maximum_wei):
            raise ValueError("Minimum excess must not exceed sweep maximum")
        return self


class ModeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1)
    mode: Literal["plan_only", "execute", "off"]
    confirm_standing_permission: bool = False
