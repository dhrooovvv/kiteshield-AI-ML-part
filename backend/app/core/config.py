"""
KiteShield Wallet — Application Configuration

Loads and validates all configuration from environment variables.
Fails at startup if required settings are missing or invalid.

Security: Never logs or exposes secret values.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


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
            raise ValueError(
                "EMERGENCY_STOP_ADMIN_API_KEY must be set to a real secret"
            )
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins."""
        return [origin.strip() for origin in self.app_cors_origins.split(",") if origin.strip()]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.

    Raises ValidationError at startup if required settings are missing.
    This is intentional fail-fast behavior.
    """
    return Settings()
