"""The model returns fields, never a recipient, decision, instruction or tool call."""

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas import validate_eth_address
from app.services.amounts import eth_to_wei


class InvoiceFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    vendor_name: str = Field(min_length=1, max_length=120)
    invoice_number: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$")
    amount_eth: str = Field(min_length=1, max_length=80)
    due_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("vendor_name")
    @classmethod
    def exact_name(cls, value):
        if value != value.strip() or not value.isascii():
            raise ValueError("Vendor names must be exact, printable ASCII")
        if any(ord(char) < 32 for char in value):
            raise ValueError("Invalid vendor name")
        return value

    @field_validator("amount_eth")
    @classmethod
    def amount(cls, value):
        eth_to_wei(value)
        return value

    @field_validator("due_date")
    @classmethod
    def valid_date(cls, value):
        date.fromisoformat(value)
        return value


class VendorInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=120)
    payout_address: str
    maximum_eth: str
    expected_version: int = Field(ge=0)
    active: bool = True

    @field_validator("name")
    @classmethod
    def name_is_exact(cls, value):
        return InvoiceFields.exact_name(value)

    @field_validator("payout_address")
    @classmethod
    def address(cls, value):
        if int(value, 16) == 0:
            raise ValueError("Zero recipient is forbidden")
        return validate_eth_address(value)

    @field_validator("maximum_eth")
    @classmethod
    def amount(cls, value):
        eth_to_wei(value)
        return value


class InvoiceTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=20000)


def vendor_id_valid(value):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value):
        raise ValueError("Invalid vendor ID")
