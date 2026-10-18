"""Authenticated public portfolio snapshot. No writes or execution interfaces."""

import logging
import re
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Annotated

import httpx
from eth_account import Account
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.live_rpc import validate_live_rpc_url
from app.core.security import verify_api_key
from app.db import get_db_session
from app.models import Policy, Proposal, SpendingRecord, Transaction
from app.schemas import APIResponse

router = APIRouter(prefix="/portfolio", tags=["Portfolio (read only)"])


class _HideProviderURL(logging.Filter):
    """HTTPX normally logs URLs at INFO, including provider credential paths."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return str(httpx.URL(get_settings().sepolia_rpc_url)) not in record.getMessage()
        except Exception:
            return False


logging.getLogger("httpx").addFilter(_HideProviderURL())


def units(value: int, decimals: int = 18) -> str:
    with localcontext() as ctx:
        ctx.prec = 120
        return format(Decimal(value) / Decimal(10) ** decimals, "f")


def share(value: int, total: int) -> str | None:
    if total == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 120
        return format((Decimal(value) * 100 / Decimal(total)).quantize(Decimal("0.000001")), "f")


def quantity(value) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,64}", value):
        raise ValueError("Malformed RPC quantity")
    return int(value, 16)


class PortfolioRPC:
    """Small explicit allowlist: no transaction submission or wallet RPC methods."""

    async def call(self, client: httpx.AsyncClient, method: str, params: list):
        if method not in {
            "eth_chainId", "eth_getBlockByNumber", "eth_getBalance",
            "eth_getTransactionCount", "eth_call",
        }:
            raise ValueError("Read-only RPC method required")
        response = await client.post(get_settings().sepolia_rpc_url, json={
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
        })
        response.raise_for_status()
        result = response.json()
        if (not isinstance(result, dict) or result.get("jsonrpc") != "2.0"
                or type(result.get("id")) is not int or result["id"] != 1
                or "error" in result or "result" not in result):
            raise ValueError("Malformed RPC response")
        return result["result"]


async def network_snapshot() -> dict:
    settings = get_settings()
    try:
        validate_live_rpc_url(settings.sepolia_rpc_url)
        # Local derivation only: no signing, no key returned or logged.
        signer = Account.from_key(settings.signer_private_key).address
        wallets = [(signer, "Signer wallet (hot)")]
        wallets += [(address, "Watched wallet") for address in settings.watched_addresses
                    if address.lower() != signer.lower()]
        rpc = PortfolioRPC()
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            chain = quantity(await rpc.call(client, "eth_chainId", []))
            if chain != 11155111:
                return {"status": "unavailable", "reason": "WRONG_CHAIN",
                        "message": "RPC chain ID is not Sepolia (11155111).",
                        "holdings": [], "pending_nonce": None}
            block = await rpc.call(client, "eth_getBlockByNumber", ["latest", False])
            number, timestamp = quantity(block["number"]), quantity(block["timestamp"])
            block_time = datetime.fromtimestamp(timestamp, UTC).isoformat()
            tag = hex(number)
            assets = [("ETH", None, 18)] + [
                (token.symbol, token.address, token.decimals) for token in settings.token_allowlist
            ]
            holdings = []
            for symbol, contract, decimals in assets:
                rows = []
                for address, role in wallets:
                    if contract is None:
                        raw = await rpc.call(client, "eth_getBalance", [address, tag])
                    else:
                        raw = await rpc.call(client, "eth_call", [{
                            "to": contract, "data": "0x70a08231" + address[2:].lower().zfill(64),
                        }, tag])
                        if not isinstance(raw, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", raw):
                            raise ValueError("Malformed token balance")
                    rows.append((address, role, quantity(raw)))
                total = sum(row[2] for row in rows)
                for address, role, value in rows:
                    holdings.append({
                        "asset": symbol, "token_address": contract, "decimals": decimals,
                        "address": address, "role": role, "balance_raw": str(value),
                        "balance": units(value, decimals), "share_percent": share(value, total),
                        "address_url": f"https://sepolia.etherscan.io/address/{address}",
                    })
            nonce = quantity(await rpc.call(client, "eth_getTransactionCount", [signer, "pending"]))
            # Refuse an inconsistent provider rather than presenting mixed-chain balances.
            if quantity(await rpc.call(client, "eth_chainId", [])) != chain:
                raise ValueError("RPC chain changed during read")
        return {"status": "available", "chain_id": chain, "network": "Sepolia",
                "block_number": number, "block_timestamp": block_time,
                "pending_nonce": nonce, "holdings": holdings,
                "allocation_basis": "Wallet share of each asset by amount; not cross-asset value",
                "valuation_notice": "testnet, no market value"}
    except Exception:
        # Provider exceptions can contain credential-bearing RPC URLs. Never return/log them.
        return {"status": "unavailable", "reason": "RPC_READ_FAILED",
                "message": "Live portfolio RPC read failed or returned malformed data.",
                "holdings": [], "pending_nonce": None}


@router.get("", response_model=APIResponse)
async def portfolio(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    snapshot = await network_snapshot()
    settings = get_settings()
    today = datetime.now(UTC).date().isoformat()
    policy = await session.scalar(select(Policy).where(Policy.is_active.is_(True))
                                  .order_by(Policy.version.desc()).limit(1))
    reservations = (await session.scalars(select(SpendingRecord))).all()
    spent = sum(int(r.amount_wei) for r in reservations
                if r.status == "COMMITTED" and r.period_date == today)
    pending = sum(int(r.amount_wei) for r in reservations if r.status == "RESERVED")
    limit = int(policy.daily_limit_wei) if policy and policy.daily_limit_wei else None
    budget = {
        "status": "available" if policy else "unavailable", "period": "UTC calendar day",
        "date": today, "policy_version": policy.version if policy else None,
        "daily_limit_eth": units(limit) if limit is not None else None,
        "spent_today_eth": units(spent), "pending_eth": units(pending),
        "remaining_eth": units(max(0, limit - spent - pending)) if limit is not None else None,
        "spent_percent": share(spent, limit) if limit else None,
        "pending_percent": share(pending, limit) if limit else None,
        "auto_execute_enabled": settings.auto_execute_enabled,
        "autonomous_cap_eth": str(settings.auto_execute_max_eth),
        "escalation_threshold_eth": units(int(policy.escalation_threshold_wei))
        if policy and policy.escalation_threshold_wei else None,
        "absolute_max_eth": units(int(policy.max_amount_wei)) if policy else None,
    }
    records = (await session.execute(select(
        Transaction.tx_hash, Transaction.execution_mode, Transaction.execution_outcome,
        Transaction.status, Transaction.created_at, Proposal.id, Proposal.amount_wei,
        Proposal.recipient, Proposal.chain_id,
    ).join(Proposal, Proposal.id == Transaction.proposal_id)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc()).limit(10))).all()
    payments = []
    for row in records:
        simulated = row.execution_mode == "simulated" or row.execution_outcome == "SIMULATED"
        real_hash = (not simulated and row.execution_mode == "sepolia" and row.chain_id == 11155111
                     and bool(re.fullmatch(r"0x[0-9a-fA-F]{64}", row.tx_hash or "")))
        payments.append({
            "proposal_id": row.id, "amount_eth": units(int(row.amount_wei)),
            "recipient": row.recipient, "status": "SIMULATED" if simulated else
            row.execution_outcome or "UNVERIFIED", "tx_hash": row.tx_hash,
            "lifecycle_status": row.status, "execution_outcome": row.execution_outcome,
            "explorer_url": f"https://sepolia.etherscan.io/tx/{row.tx_hash}" if real_hash else None,
            "created_at": row.created_at,
        })
    return APIResponse(data={"mode": settings.execution_mode, "network": snapshot,
                             "budget": budget, "recent_payments": payments})
