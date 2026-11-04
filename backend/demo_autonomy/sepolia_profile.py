"""Separate, durable Sepolia configuration. Never loads the workspace .env or wallet.

Preparing a profile generates a NEW testnet key; it does not authorize payments.
Authority is a local administrator-owned file, frozen at process startup.
"""

import json
import os
import secrets
import sys
from pathlib import Path

from eth_account import Account
from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL = "kiteshield-gemma4:12b-q4km"
DIGEST = "13478e018db994bfea035644c1774abc573381ee0ff7e11ad59f3fbc89fd1519"


class Authority(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    chain_id: int = Field(default=11155111, ge=11155111, le=11155111)
    payments_enabled: bool = False
    faucet_enabled: bool = False
    recipient: str | None = Field(default=None, pattern=r"^0x[0-9a-fA-F]{40}$")
    payment_budget_wei: int = Field(default=0, ge=0, le=10**15)
    max_payment_fee_wei: int = Field(default=0, ge=0, le=10**15)
    session_fee_budget_wei: int = Field(default=0, ge=0, le=10**15)
    funding_budget_wei: int = Field(default=0, ge=0, le=10**18)
    # The existing fixed faucet cannot accept an amount. Require a known grant
    # ceiling before using it; unexpected larger incoming funds quarantine the task.
    faucet_grant_ceiling_wei: int = Field(default=0, ge=0, le=10**18)
    max_gas_units: int = Field(default=25200, ge=21000, le=100000)
    max_fee_per_gas_wei: int = Field(default=10**9, ge=1, le=10**11)
    max_priority_fee_per_gas_wei: int = Field(default=10**8, ge=1, le=2 * 10**9)

    @model_validator(mode="after")
    def bounded(self):
        if self.payments_enabled and (
            not self.recipient
            or int(self.recipient, 16) == 0
            or not self.payment_budget_wei
            or not self.max_payment_fee_wei
            or self.session_fee_budget_wei < self.max_payment_fee_wei
        ):
            raise ValueError("Explicit recipient, payment budget and fee budgets required")
        if self.faucet_enabled and (
            not self.faucet_grant_ceiling_wei
            or self.funding_budget_wei < self.faucet_grant_ceiling_wei
        ):
            raise ValueError("Faucet grant ceiling must fit the funding budget")
        return self


def private_json(path, payload):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(payload, stream, indent=2)


def prepare(directory: Path, rpc_url: str):
    # Importing app settings would be premature here: URL syntax is checked again
    # by the existing startup gate after env-file loading has been disabled.
    from urllib.parse import urlsplit

    if urlsplit(rpc_url).scheme != "https":
        raise ValueError("HTTPS Sepolia RPC required")
    if not directory.name.startswith("kiteshield-sepolia-"):
        raise ValueError("Dedicated kiteshield-sepolia-* profile required")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    wallet = Account.create()
    private_json(
        directory / "wallet.json",
        {
            "address": wallet.address,
            "private_key": wallet.key.hex(),
            "chain_id": 11155111,
        },
    )
    private_json(directory / "connection.json", {"rpc_url": rpc_url})
    private_json(directory / "authority.json", Authority().model_dump())
    credentials = {
        name: secrets.token_urlsafe(32)
        for name in ("proposer", "approver", "policyAdmin", "emergencyAdmin")
    }
    credentials["capability"] = secrets.token_hex(32)
    private_json(directory / "credentials.json", credentials)
    return {
        "address": wallet.address,
        "chain_id": 11155111,
        "profile": str(directory),
        "payments_enabled": False,
        "faucet_enabled": False,
    }


def read_private(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("Profile files must be private regular files (0600)")
    return json.loads(path.read_text())


def bootstrap(directory: Path):
    if any(name == "app" or name.startswith("app.") for name in sys.modules):
        raise RuntimeError("Separate Sepolia process must bootstrap before app imports")
    directory = directory.resolve()
    if not directory.name.startswith("kiteshield-sepolia-") or directory.stat().st_mode & 0o077:
        raise RuntimeError("Dedicated private Sepolia profile required")
    wallet = read_private(directory / "wallet.json")
    connection = read_private(directory / "connection.json")
    authority = Authority.model_validate(read_private(directory / "authority.json"))
    credentials = read_private(directory / "credentials.json")
    if (
        wallet.get("chain_id") != 11155111
        or Account.from_key(wallet["private_key"]).address != wallet["address"]
        or wallet["private_key"].removeprefix("0x") == "b" * 64
    ):
        raise ValueError("Separate wallet identity mismatch")
    provider = (
        read_private(directory / "faucet-credentials.json") if authority.faucet_enabled else {}
    )
    keep = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "PYTHONPATH") if k in os.environ}
    os.environ.clear()
    os.environ.update(keep)
    os.chdir(directory)
    os.environ.update(
        {
            "APP_ENV": "test",
            "APP_DEBUG": "false",
            "APP_LOG_LEVEL": "ERROR",
            "DATABASE_URL": f"sqlite+aiosqlite:///{directory / 'wallet-sepolia.sqlite3'}",
            "CAPABILITY_TOKEN_SECRET": credentials["capability"],
            "SIGNER_PRIVATE_KEY": wallet["private_key"],
            "API_KEY": credentials["proposer"],
            "APPROVER_API_KEY": credentials["approver"],
            "POLICY_ADMIN_API_KEY": credentials["policyAdmin"],
            "EMERGENCY_STOP_ADMIN_API_KEY": credentials["emergencyAdmin"],
            "EXECUTION_MODE": "sepolia",
            "CHAIN_ID": "11155111",
            "SEPOLIA_RPC_URL": connection["rpc_url"],
            "MAX_GAS_UNITS": str(authority.max_gas_units),
            "MAX_FEE_PER_GAS_WEI": str(authority.max_fee_per_gas_wei),
            "MAX_PRIORITY_FEE_PER_GAS_WEI": str(authority.max_priority_fee_per_gas_wei),
            "AUTO_EXECUTE_ENABLED": "false",
            "INVOICE_INTAKE_ENABLED": "false",
            "INVOICE_LIVE_EXECUTION_ENABLED": "false",
            "TREASURY_MONITOR_ENABLED": "false",
            "INVOICE_LEARNED_SCREENING_ENABLED": "false",
            "LEARNED_SCREENING_ENABLED": "false",
            "AUTONOMY_ENABLED": "false",
            "INVOICE_MODEL": MODEL,
            "FAUCET_ENABLED": str(authority.faucet_enabled).lower(),
            "FAUCET_MODE": "sepolia",
            "OPENAI_API_KEY": "",
            "CDP_API_KEY_ID": provider.get("id", ""),
            "CDP_API_KEY_SECRET": provider.get("secret", ""),
        }
    )
    from app.core.config import Settings, get_settings

    Settings.model_config = {**Settings.model_config, "env_file": None}
    get_settings.cache_clear()
    settings = get_settings()
    settings.app_port = 8001
    settings.app_cors_origins = (
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"
    )
    # These are caller restrictions on every envelope, not replacement signing.
    return settings, authority, wallet["address"], credentials
