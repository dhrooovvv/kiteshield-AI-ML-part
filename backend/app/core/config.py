"""
KiteShield Wallet — Application Configuration

Loads and validates all configuration from environment variables.
Fails at startup if required settings are missing or invalid.

Security: Never logs or exposes secret values.
"""

from decimal import Decimal
from functools import lru_cache
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class PortfolioToken(BaseModel):
    symbol: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9._-]+$")
    address: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    decimals: int = Field(ge=0, le=36)


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All security-sensitive fields use SecretStr-like patterns
    but are kept as str for compatibility with downstream libraries.
    They are excluded from repr/logging via repr=False.
    """

    # ---- Application ----
    app_env: str = Field(
        default="development",
        description="Environment: development, staging, production",
    )
    app_debug: bool = Field(default=False, description="Enable debug mode")
    app_host: str = Field(default="127.0.0.1", description="Server bind host")
    app_port: int = Field(default=8000, description="Server bind port")
    app_log_level: str = Field(default="INFO", description="Logging level")
    app_cors_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated CORS origins",
    )

    # ---- Database ----
    database_url: str = Field(
        default="sqlite+aiosqlite:///./kiteshield.db",
        description="Database connection URL",
    )

    # ---- Security (repr=False to prevent logging) ----
    capability_token_secret: str = Field(
        ...,
        repr=False,
        min_length=64,
        description="HS256 signing secret for capability tokens (hex, ≥ 64 chars / 32 bytes)",
    )
    api_key: str = Field(
        ...,
        repr=False,
        min_length=16,
        description="API key for backend authentication",
    )
    emergency_stop_admin_api_key: str = Field(
        ...,
        repr=False,
        min_length=16,
        description="Dedicated credential for emergency-stop administration",
    )
    approver_api_key: str = Field(default="", repr=False)
    policy_admin_api_key: str = Field(default="", repr=False)
    demo_admin_api_key: str = Field(default="", repr=False)
    learned_screening_enabled: bool = Field(default=False)
    auto_execute_enabled: bool = Field(default=False)
    auto_execute_max_eth: Decimal = Field(default=Decimal("0.0001"), gt=0, decimal_places=18)
    execution_mode: Literal["simulated", "sepolia"] = Field(default="simulated")
    watched_addresses: list[str] = Field(default_factory=list, max_length=10)
    token_allowlist: list[PortfolioToken] = Field(default_factory=list, max_length=8)

    @field_validator("watched_addresses")
    @classmethod
    def public_watch_addresses(cls, values: list[str]) -> list[str]:
        import re

        if any(not re.fullmatch(r"0x[0-9a-fA-F]{40}", value) for value in values):
            raise ValueError("WATCHED_ADDRESSES must contain public Ethereum addresses only")
        return list(dict.fromkeys(value.lower() for value in values))

    max_gas_units: int = Field(default=100_000, ge=21_000, le=1_000_000)
    max_fee_per_gas_wei: int = Field(default=100_000_000_000, gt=0)
    max_priority_fee_per_gas_wei: int = Field(default=2_000_000_000, gt=0)

    # ---- Blockchain ----
    chain_id: int = Field(default=11155111, description="Target chain ID (Sepolia=11155111)")
    sepolia_rpc_url: str = Field(
        ...,
        description="Sepolia RPC endpoint URL",
    )
    signer_private_key: str = Field(
        ...,
        repr=False,
        min_length=64,
        description="Testnet-only private key (hex, without 0x prefix)",
    )

    # ---- OpenAI ----
    openai_api_key: str = Field(
        default="",
        repr=False,
        description="OpenAI API key (optional for mock agent mode)",
    )
    openai_model: str = Field(default="gpt-4o", description="OpenAI model name")

    # ---- Prompt-injection ensemble ----
    ai_ml_horizon_model_id: str = Field(
        default="Horizon-Labs/prompt-injection-guard-base",
        description="Local Horizon model identifier",
    )
    ai_ml_bastion_model_id: str = Field(
        default="bastionsoft/binary-bastion-prompt-protection-deberta-v3-xsmall-v1",
        description="Bastion model identifier used by the installed guard package",
    )
    ai_ml_bastion_threshold: float = Field(default=0.059, ge=0.0, le=1.0)
    ai_ml_horizon_classification_method: Literal["argmax", "threshold"] = Field(default="argmax")
    ai_ml_horizon_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    ai_ml_device: str = Field(default="cpu")
    ai_ml_local_files_only: bool = Field(default=True)
    ai_ml_inference_timeout_seconds: float = Field(default=30.0, gt=0.0, le=120.0)
    ai_ml_max_prompt_length: int = Field(default=2000, gt=0, le=20_000)

    # ---- Token Settings ----
    capability_token_ttl_seconds: int = Field(
        default=120,
        ge=10,
        le=600,
        description="Capability token lifetime in seconds",
    )
    approval_expiry_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Approval request expiry in seconds",
    )
    clock_skew_seconds: int = Field(
        default=30,
        ge=0,
        le=120,
        description="Clock skew tolerance for token verification",
    )

    @field_validator("chain_id")
    @classmethod
    def validate_chain_id(cls, v: int) -> int:
        """Restrict to Sepolia testnet for MVP safety."""
        if v != 11155111:
            raise ValueError(
                f"Chain ID must be 11155111 (Sepolia) for MVP. Got: {v}. "
                "Mainnet and other chains are explicitly excluded."
            )
        return v

    @field_validator("capability_token_secret")
    @classmethod
    def validate_token_secret(cls, v: str) -> str:
        """Ensure token secret is not the placeholder value."""
        if "CHANGE_ME" in v:
            raise ValueError(
                "CAPABILITY_TOKEN_SECRET must be set to a real secret. "
                'Generate with: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return v

    @field_validator("signer_private_key")
    @classmethod
    def validate_signer_key(cls, v: str) -> str:
        """Ensure signer key is not the placeholder value."""
        if "CHANGE_ME" in v:
            raise ValueError(
                "SIGNER_PRIVATE_KEY must be set to a real testnet private key. "
                "See .env.example for generation instructions."
            )
        # Strip 0x prefix if present
        return v.removeprefix("0x")

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Ensure API key is not the placeholder value."""
        if "CHANGE_ME" in v:
            raise ValueError(
                "API_KEY must be set. "
                'Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return v

    @field_validator("emergency_stop_admin_api_key")
    @classmethod
    def validate_emergency_stop_admin_api_key(cls, v: str) -> str:
        """Reject placeholder emergency-stop credentials."""
        if "CHANGE_ME" in v:
            raise ValueError("EMERGENCY_STOP_ADMIN_API_KEY must be set to a real secret")
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins."""
        return [origin.strip() for origin in self.app_cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def distinct_roles(self) -> Self:
        values = [self.api_key, self.emergency_stop_admin_api_key]
        for key in (self.approver_api_key, self.policy_admin_api_key, self.demo_admin_api_key):
            if key:
                if len(key) < 16 or "CHANGE_ME" in key:
                    raise ValueError(
                        "Role credentials must be non-placeholder secrets of at least 16 characters"
                    )
                values.append(key)
        if len(values) != len(set(values)):
            raise ValueError(
                "Proposer, approver, policy administrator, and emergency credentials must differ"
            )
        if self.app_env == "demo" and (
            self.execution_mode != "simulated"
            or self.database_url != "sqlite+aiosqlite:///./kiteshield-demo.db"
            # Public test fixture, NOT a secret or an owner's wallet identity.
            or self.signer_private_key != "b" * 64
            or self.app_debug
        ):
            raise ValueError(
                "Demo requires simulation, the isolated kiteshield-demo.db database, "
                "the public test signer fixture, and debug logging disabled"
            )
        if (
            self.execution_mode == "sepolia"
            and self.database_url.rsplit("/", 1)[-1].split("?", 1)[0] == "kiteshield-demo.db"
        ):
            raise ValueError("The demo database must never be opened for live Sepolia execution")
        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
        "hide_input_in_errors": True,
    }


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.

    Raises ValidationError at startup if required settings are missing.
    This is intentional fail-fast behavior.
    """
    return Settings()
