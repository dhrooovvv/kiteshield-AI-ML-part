"""READ ONLY: fee/funding preview. Never signs, sends, or changes configuration.

Run from backend: ./.venv/bin/python scripts/preview_sepolia_payments.py --recipient 0x...
The signer wallet must be confirmed by its owner as dedicated to Sepolia testing.
"""

import argparse
import asyncio
import json

from eth_account import Account

from app.core.config import get_settings
from app.db import get_session_factory
from app.schemas import NormalizedAction, validate_eth_address
from app.services.amounts import eth_to_wei, wei_to_eth
from app.services.blockchain import BlockchainService


async def preview(recipient: str, amounts: list[str]) -> dict:
    settings = get_settings()
    # Only this read-only process uses live RPC, even when the application is
    # simulated. No setting is saved; no execution record is created.
    settings.execution_mode = "sepolia"
    recipient = validate_eth_address(recipient)
    sender = Account.from_key(settings.signer_private_key).address
    blockchain = BlockchainService()
    payments = []
    first_nonce = None
    async with get_session_factory()() as session:
        for index, amount in enumerate(amounts):
            action = NormalizedAction(
                proposal_id=f"preview-{index}",
                correlation_id="read-only-preview",
                recipient=recipient,
                amount_wei=int(eth_to_wei(amount)),
                chain_id=11155111,
            )
            envelope = await blockchain.prepare_transaction(session, sender, action)
            if first_nonce is None:
                first_nonce = envelope["nonce"]
            candidate_nonce = first_nonce + index
            if envelope["nonce"] > candidate_nonce:
                raise ValueError("Nonce state changed during preview; run a fresh preview")
            maximum_fee = envelope["gas"] * envelope["maxFeePerGas"]
            # prepare_transaction uses maxFee = 2 * baseFee + priorityFee.
            estimated_fee = envelope["gas"] * (
                (envelope["maxFeePerGas"] - envelope["maxPriorityFeePerGas"]) // 2
                + envelope["maxPriorityFeePerGas"]
            )
            payments.append(
                {
                    "sender": sender,
                    "recipient": recipient,
                    "chain_id": 11155111,
                    "candidate_nonce": candidate_nonce,
                    "amount_eth": wei_to_eth(action.amount_wei),
                    "amount_wei": str(action.amount_wei),
                    "gas_limit": envelope["gas"],
                    "max_fee_per_gas_wei": str(envelope["maxFeePerGas"]),
                    "max_priority_fee_per_gas_wei": str(envelope["maxPriorityFeePerGas"]),
                    "estimated_fee_wei": str(estimated_fee),
                    "maximum_fee_exposure_wei": str(maximum_fee),
                    "maximum_total_cost_wei": str(action.amount_wei + maximum_fee),
                }
            )
    balance = await blockchain.get_balance(sender)
    required = sum(int(p["amount_wei"]) + int(p["maximum_fee_exposure_wei"]) for p in payments)
    return {
        "status": "PREVIEW_ONLY_NOT_AUTHORIZED_NOT_SIGNED",
        "payments": payments,
        "balance_wei": str(balance),
        "required_balance_upper_bound_wei": str(required),
        "sufficient_funds": balance >= required,
        "approver_configured": bool(settings.approver_api_key),
        "policy_administrator_configured": bool(settings.policy_admin_api_key),
        "warning": (
            "Fees must be refreshed before authorization. "
            "Nonces are not reserved by this preview."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--amounts", nargs=2, default=["0.00001", "0.00002"])
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(preview(args.recipient, args.amounts)), indent=2))
    except Exception as exc:
        # RPC exceptions may contain credential-bearing URLs; do not print them.
        print(
            json.dumps(
                {
                    "status": "PREVIEW_UNAVAILABLE",
                    "error_type": type(exc).__name__,
                    "action": "Check database initialization, Sepolia RPC, recipient and funding",
                }
            )
        )
        raise SystemExit(1) from None
