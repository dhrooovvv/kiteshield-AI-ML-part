"""Read-only, fail-closed RPC verification before live application startup."""

import re
from datetime import UTC, datetime
from ipaddress import ip_address
from urllib.parse import unquote, urlsplit

import httpx

from app.core.config import Settings


def validate_live_rpc_url(url: str) -> None:
    """Reject insecure, placeholder and local/mock endpoints without exposing secrets."""
    invalid = RuntimeError("Live Sepolia requires a non-placeholder HTTPS RPC endpoint")
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        raise invalid from None
    decoded = unquote(url).lower()
    placeholders = (
        "your_api_key", "your-api-key", "your_key", "your-key",
        "change_me", "changeme", "placeholder", "<", ">",
    )
    if (
        parsed.scheme != "https"
        or not host
        or parsed.fragment
        or port == 0
        or "mock" in host
        or host == "localhost"
        or host.endswith((
            ".localhost", ".local", ".localdomain", ".internal", ".test", ".invalid",
            ".example.com", ".example.org", ".example.net",
        ))
        or host in {"example.com", "example.org", "example.net"}
        or any(value in decoded for value in placeholders)
        or re.search(r"your[_-][a-z0-9_-]*(?:key|token)|api[_-]?key[_-]?here", decoded)
    ):
        raise invalid
    try:
        address = ip_address(host)
    except ValueError:
        # Also exclude legacy numeric loopback spellings accepted by some clients.
        if host.isdigit() or all(part.isdigit() for part in host.split(".")):
            raise invalid from None
    else:
        if not address.is_global:
            raise invalid


async def verify_live_rpc(settings: Settings) -> dict | None:
    """Only eth_chainId and eth_blockNumber are permitted in this startup gate."""
    if settings.execution_mode != "sepolia":
        return None
    validate_live_rpc_url(settings.sepolia_rpc_url)

    async def quantity(client: httpx.AsyncClient, method: str, request_id: int) -> int:
        try:
            response = await client.post(
                settings.sepolia_rpc_url,
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": []},
            )
            response.raise_for_status()
            payload = response.json()
            if (
                not isinstance(payload, dict)
                or payload.get("jsonrpc") != "2.0"
                or type(payload.get("id")) is not int
                or payload["id"] != request_id
                or "error" in payload
                or not isinstance(payload.get("result"), str)
                or not re.fullmatch(r"0x[0-9a-fA-F]+", payload["result"])
            ):
                raise ValueError("Invalid RPC quantity")
            return int(payload["result"], 16)
        except Exception:
            # HTTP/RPC errors can contain the credential-bearing URL or provider text.
            raise RuntimeError(f"Live Sepolia startup check failed: {method}") from None

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        chain_id = await quantity(client, "eth_chainId", 1)
        if chain_id != 11155111:
            raise RuntimeError("Live Sepolia startup refused: expected chain ID 11155111")
        block_number = await quantity(client, "eth_blockNumber", 2)
    return {
        "chain_id": chain_id,
        "block_number": block_number,
        "verified_at": datetime.now(UTC).isoformat(),
    }
