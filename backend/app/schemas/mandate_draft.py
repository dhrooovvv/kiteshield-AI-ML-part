"""Draft-only values: absence means clarification, never implicit authority."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    instruction: str = Field(min_length=1, max_length=2000)


class DraftValues(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target_balance_eth: str | None = None
    recipient_alias: str | None = None
    max_actions_per_day: int | None = Field(default=None, ge=1, le=100)
    sweep_maximum_eth: str | None = None
    minimum_excess_eth: str | None = None
    cooldown_seconds: int | None = Field(default=None, ge=60, le=86400)
    freshness_seconds: int | None = Field(default=None, ge=15, le=300)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("target_balance_eth", "sweep_maximum_eth", "minimum_excess_eth")
    @classmethod
    def decimal_string(cls, v):
        if v is not None and not re.fullmatch(r"(?:0|[1-9][0-9]{0,6})(?:\.[0-9]{1,18})?", v):
            raise ValueError("Use a plain bounded decimal ETH string")
        return v


class DraftResult(BaseModel):
    status: Literal["draft", "clarification", "refused", "invalid", "could_not_interpret"]
    draft: DraftValues | None = None
    resolved_recipient: str | None = None
    source: Literal["parser", "llm", "none"] = "none"
    validation: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=lambda: [
            (
                "Draft only. Nothing saved, enabled, proposed or executed. Review all values "
                "before saving."
            )
        ]
    )
