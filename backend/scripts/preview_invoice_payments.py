"""Read-only Sepolia quotes for the three invoice examples. Never signs or submits."""

import asyncio
import json
from datetime import UTC, datetime

from eth_account import Account
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models import Policy
from app.schemas import NormalizedAction
from app.services.blockchain import BlockchainService

RECIPIENT = "0x229D5588641f2614e3F486c853D8BA0eC5FFe811"
SENDER = "0x3807fc9c3A8adF2d465290bbf06AE769DD08Ada7"
AMOUNTS_WEI = (10**13, 2 * 10**13, 3 * 10**13)


async def preview():
    settings = get_settings()
    sender = Account.from_key(settings.signer_private_key).address
    if settings.execution_mode != "sepolia" or settings.chain_id != 11155111 or sender != SENDER:
        raise ValueError("EXPECTED_SEPOLIA_TEST_SENDER_REQUIRED")
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            policy = await session.scalar(select(Policy).where(Policy.is_active.is_(True)))
            if policy is None or RECIPIENT.lower() not in {
                address.lower() for address in json.loads(policy.allowed_recipients)
            }:
                raise ValueError("RECIPIENT_NOT_ALLOWLISTED")
            blockchain = BlockchainService()
            quotes = []
            for index, amount in enumerate(AMOUNTS_WEI):
                action = NormalizedAction(
                    proposal_id=f"read-only-invoice-{index + 1}",
                    correlation_id=f"read-only-invoice-{index + 1}",
                    recipient=RECIPIENT,
                    amount_wei=amount,
                    chain_id=11155111,
                )
                envelope = await blockchain.prepare_transaction(session, sender, action)
                if quotes and envelope["nonce"] != quotes[0]["pending_candidate_nonce"]:
                    raise ValueError("NONCE_CHANGED_DURING_PREVIEW")
                quotes.append(
                    {
                        "example": index + 1,
                        "amount_wei": str(amount),
                        "pending_candidate_nonce": envelope["nonce"],
                        "candidate_nonce": envelope["nonce"] + index,
                        "gas_limit": envelope["gas"],
                        "max_fee_per_gas_wei": str(envelope["maxFeePerGas"]),
                        "priority_fee_per_gas_wei": str(envelope["maxPriorityFeePerGas"]),
                        "maximum_fee_wei": str(envelope["gas"] * envelope["maxFeePerGas"]),
                        "maximum_total_wei": str(
                            amount + envelope["gas"] * envelope["maxFeePerGas"]
                        ),
                    }
                )
            balance = await blockchain.get_balance(sender)
            combined = sum(int(quote["maximum_total_wei"]) for quote in quotes)
            return {
                "read_only": True,
                "authorized_to_broadcast": False,
                "observed_at_utc": datetime.now(UTC).isoformat(),
                "sender": sender,
                "recipient": RECIPIENT,
                "chain_id": 11155111,
                "policy_version": policy.version,
                "balance_wei": str(balance),
                "balance_sufficient": balance >= combined,
                "quotes": quotes,
                "combined_maximum_total_wei": str(combined),
                "note": "Provisional nonces; re-estimate after each confirmed payment. "
                "No reservation, proposal, signature or broadcast was created.",
            }
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(preview()), indent=2))
    except Exception as error:
        # Provider messages may contain endpoint credentials; never echo them.
        print(
            json.dumps({"read_only": True, "available": False, "error_type": type(error).__name__})
        )
        raise SystemExit(1) from None
