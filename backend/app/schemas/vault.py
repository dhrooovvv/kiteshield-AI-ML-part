"""Exact vault call templates; arbitrary calldata is not an input type."""

import hashlib
import json
from enum import StrEnum

from eth_abi import encode
from pydantic import BaseModel, ConfigDict, Field, field_validator
from web3 import Web3

from app.schemas import NormalizedAction, validate_eth_address


class VaultKind(StrEnum):
    DEPLOY = "DEPLOY"
    CONFIGURE = "CONFIGURE"
    DEPOSIT = "DEPOSIT"
    GAS_FUND = "GAS_FUND"
    PAY = "PAY"
    TIGHTEN = "TIGHTEN"
    PAUSE = "PAUSE"
    OWNER_PAUSE = "OWNER_PAUSE"
    RESUME = "RESUME"
    RECOVER = "RECOVER"


class VaultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: VaultKind
    owner: str
    agent: str
    recipient: str
    vault: str | None = None
    amount_wei: int = Field(default=0, ge=0, le=10**18)
    budget_wei: int = Field(default=0, ge=0, le=10**15)
    per_payment_wei: int = Field(default=0, ge=0, le=10**15)
    expires: int = Field(default=0, ge=0)
    session_nonce: int = Field(default=0, ge=0)
    epoch: int = Field(default=0, ge=0)
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("owner", "agent", "recipient")
    @classmethod
    def addresses(cls, value):
        return validate_eth_address(value)

    @field_validator("vault")
    @classmethod
    def vault_address(cls, value):
        return validate_eth_address(value) if value is not None else None

    def digest(self):
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @property
    def agent_operation(self):
        return self.kind in {VaultKind.PAY, VaultKind.TIGHTEN, VaultKind.PAUSE}

    def encode(self, bytecode):
        if self.kind == VaultKind.DEPLOY:
            return None, 0, bytecode + encode(["address"], [self.owner]).hex()
        if self.kind == VaultKind.DEPOSIT:
            return self.vault, self.amount_wei, "0x"
        if self.kind == VaultKind.GAS_FUND:
            return self.agent, self.amount_wei, "0x"
        options = {
            VaultKind.CONFIGURE: (
                "configure(address,address,uint256,uint256,uint256)",
                ["address", "address", "uint256", "uint256", "uint256"],
                [self.agent, self.recipient, self.budget_wei, self.per_payment_wei, self.expires],
            ),
            VaultKind.PAY: (
                "pay(uint256,uint256,uint256)",
                ["uint256"] * 3,
                [self.amount_wei, self.session_nonce, self.epoch],
            ),
            VaultKind.TIGHTEN: (
                "tighten(uint256,uint256,uint256)",
                ["uint256"] * 3,
                [self.budget_wei, self.per_payment_wei, self.expires],
            ),
            VaultKind.PAUSE: ("pause()", [], []),
            VaultKind.OWNER_PAUSE: ("pause()", [], []),
            VaultKind.RESUME: ("resume()", [], []),
            VaultKind.RECOVER: ("recover(uint256)", ["uint256"], [self.amount_wei]),
        }
        signature, types, values = options[self.kind]
        selector = Web3.keccak(text=signature)[:4].hex()
        return self.vault, 0, "0x" + selector.removeprefix("0x") + encode(types, values).hex()


class VaultPayoutAction(NormalizedAction):
    operation_id: str
    vault_digest: str

    def canonical_string(self, nonce):
        return (
            "VAULT_V1:"
            + super().canonical_string(nonce)
            + ":"
            + self.operation_id
            + ":"
            + self.vault_digest
        )

    def action_digest_without_nonce(self):
        value = (
            f"VAULT_V1:{self.chain_id}:{self.action_type.value}:{self.recipient.lower()}:"
            f"{self.amount_wei}:{self.operation_id}:{self.vault_digest}"
        )
        return hashlib.sha256(value.encode()).hexdigest()


class VaultExecutionLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation_id: str
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_fee_wei: int = Field(gt=0, le=10**18)

    def check(self, operation):
        from app.exceptions import SigningRejectedError

        envelope = json.loads(operation.envelope)
        if (
            operation.id != self.operation_id
            or operation.authority_digest != self.payload_digest
            or hashlib.sha256(operation.envelope.encode()).hexdigest() != self.envelope_digest
            or envelope["gas"] * envelope["maxFeePerGas"] > self.max_fee_wei
        ):
            raise SigningRejectedError("Vault execution exceeds caller's exact reserved limits")
