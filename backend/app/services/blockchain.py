"""
KiteShield Wallet — Blockchain Service

Adapter for Ethereum Sepolia testnet interactions.
Submits signed transactions, queries balances, and tracks confirmation.

Security:
- Never touches private keys. Only accepts pre-signed raw transaction hex.
- Enforces chain ID check (Sepolia: 11155111).
- Graceful error handling for RPC outages and network timeouts.
"""

import asyncio
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import Web3

from app.core.config import get_settings
from app.core.logging import get_logger
from app.exceptions import RPCError, TransactionSubmissionError
from app.models import ExecutionAttempt
from app.schemas import NormalizedAction
from app.services.emergency_stop import EmergencyStopService
from app.services.execution_lock import lock_execution

logger = get_logger("blockchain")
emergency_stop_service = EmergencyStopService()


class BlockchainService:
    """Ethereum Sepolia blockchain adapter."""

    def __init__(self, rpc_url: str | None = None) -> None:
        settings = get_settings()
        self._rpc_url = rpc_url or settings.sepolia_rpc_url
        self._chain_id = settings.chain_id
        self._w3: Web3 | None = None

    def _get_w3(self) -> Web3:
        """Lazily initialize Web3 instance."""
        if self._w3 is None:
            self._w3 = Web3(Web3.HTTPProvider(self._rpc_url, request_kwargs={"timeout": 10}))
        return self._w3

    async def prepare_transaction(
        self, session: AsyncSession, sender: str, action: NormalizedAction
    ) -> dict[str, Any]:
        settings = get_settings()
        simulated = settings.execution_mode == "simulated"
        if simulated:
            pending, gas, base, priority = 0, 21_000, 1_000_000_000, 1_000_000_000
        else:

            def preflight() -> tuple[int, int, int, int]:
                w3 = self._get_w3()
                if action.chain_id != 11155111 or w3.eth.chain_id != 11155111:
                    raise TransactionSubmissionError("RPC chain identity mismatch")
                if w3.eth.get_code(action.recipient):
                    raise TransactionSubmissionError(
                        "Contract recipients are not supported by this native payment workflow"
                    )
                pending = w3.eth.get_transaction_count(sender, "pending")
                gas = w3.eth.estimate_gas(
                    {"from": sender, "to": action.recipient, "value": action.amount_wei}
                )
                base = int(w3.eth.get_block("latest")["baseFeePerGas"])
                priority = max(
                    1, min(int(w3.eth.max_priority_fee), settings.max_priority_fee_per_gas_wei)
                )
                return pending, gas, base, priority

            try:
                pending, gas, base, priority = await asyncio.to_thread(preflight)
            except TransactionSubmissionError:
                raise
            except Exception as exc:
                raise RPCError("Transaction preflight failed") from exc
        legacy = await session.scalar(
            select(ExecutionAttempt.id)
            .where(
                ExecutionAttempt.sender == sender.lower(),
                ExecutionAttempt.chain_id == action.chain_id,
                ExecutionAttempt.execution_mode.is_(None),
                ExecutionAttempt.status.in_(("PREPARED", "SIGNED", "UNCERTAIN", "SUBMITTED")),
            )
            .limit(1)
        )
        if legacy is not None:
            raise TransactionSubmissionError(
                "Legacy execution mode is unknown; reconcile it before allocating a nonce"
            )
        last = await session.scalar(
            select(func.max(ExecutionAttempt.nonce)).where(
                ExecutionAttempt.sender == sender.lower(),
                ExecutionAttempt.chain_id == action.chain_id,
                ExecutionAttempt.execution_mode == settings.execution_mode,
            )
        )
        nonce = max(pending, (last + 1) if last is not None else 0)
        fee = 2 * base + priority
        gas = (gas * 120 + 99) // 100
        if gas > settings.max_gas_units or fee > settings.max_fee_per_gas_wei:
            raise TransactionSubmissionError("Estimated gas or fee exceeds configured bounds")
        return {
            "to": Web3.to_checksum_address(action.recipient),
            "value": action.amount_wei,
            "chainId": action.chain_id,
            "nonce": nonce,
            "gas": gas,
            "maxFeePerGas": fee,
            "maxPriorityFeePerGas": priority,
            "type": 2,
        }

    async def submit_raw_transaction(
        self, raw_tx_hex: str, *, session: AsyncSession
    ) -> dict[str, Any]:
        """Broadcast a pre-signed transaction to the Sepolia network.

        Args:
            raw_tx_hex: Hex-encoded raw signed transaction (with or without 0x prefix).

        Returns:
            Dict containing tx_hash and submission status.

        Raises:
            TransactionSubmissionError: If submission fails or node rejects the tx.
            RPCError: If the RPC endpoint is unreachable or times out.
        """
        await lock_execution(session)
        await emergency_stop_service.require_running(session)
        cleaned_hex = raw_tx_hex.removeprefix("0x")
        logger.info("Broadcasting raw transaction (length=%d hex chars)", len(cleaned_hex))

        attempt = await session.scalar(
            select(ExecutionAttempt).where(ExecutionAttempt.raw_transaction == raw_tx_hex)
        )
        if not attempt or attempt.status not in ("SIGNED", "UNCERTAIN"):
            raise TransactionSubmissionError("No durable signed execution owns this payload")
        from app.models import Proposal
        from app.services.authorization import validate_authorization

        proposal = await session.get(Proposal, attempt.proposal_id)
        if proposal is None:
            raise TransactionSubmissionError("Execution proposal is unavailable")
        action = NormalizedAction(
            proposal_id=proposal.id,
            correlation_id=proposal.correlation_id,
            recipient=proposal.recipient,
            amount_wei=int(proposal.amount_wei),
            chain_id=proposal.chain_id,
        )
        await validate_authorization(session, action, attempt.policy_version, attempt.approval_id)
        from eth_account import Account

        if (
            attempt.execution_mode != get_settings().execution_mode
            or Account.recover_transaction(raw_tx_hex).lower() != attempt.sender
            or "0x" + Web3.keccak(bytes.fromhex(cleaned_hex)).hex().removeprefix("0x")
            != attempt.tx_hash
        ):
            raise TransactionSubmissionError("Signed payload does not match its execution owner")
        await emergency_stop_service.require_running(session)

        # Check for test / mock RPC environment
        settings = get_settings()
        if settings.execution_mode == "simulated":
            # Deterministic mock hash for test execution
            mock_hash = "0x" + Web3.keccak(bytes.fromhex(cleaned_hex)).hex().removeprefix("0x")
            logger.info("Test/Mock environment detected. Returning mock tx_hash: %s", mock_hash)
            return {
                "tx_hash": mock_hash,
                "status": "SUBMITTED",
                "network": "simulated-no-broadcast",
            }

        try:
            w3 = self._get_w3()
            if await asyncio.to_thread(lambda: w3.eth.chain_id) != self._chain_id:
                raise TransactionSubmissionError("RPC chain identity mismatch")
            await emergency_stop_service.require_running(session)
            tx_bytes = bytes.fromhex(cleaned_hex)
            tx_hash_bytes = await asyncio.to_thread(w3.eth.send_raw_transaction, tx_bytes)
            tx_hash_hex = tx_hash_bytes.hex()
            if not tx_hash_hex.startswith("0x"):
                tx_hash_hex = "0x" + tx_hash_hex

            logger.info("Transaction broadcast successful: tx_hash=%s", tx_hash_hex)
            return {
                "tx_hash": tx_hash_hex,
                "status": "SUBMITTED",
                "network": "sepolia",
            }
        except Exception as e:
            raise TransactionSubmissionError(
                "Submission outcome unknown; retain the signed execution for reconciliation"
            ) from e

    async def get_balance(self, address: str) -> int:
        """Fetch native ETH balance in wei for an address."""
        settings = get_settings()
        if settings.execution_mode == "simulated":
            return 10_000_000_000_000_000_000  # 10 ETH in test mode

        try:
            w3 = self._get_w3()
            checksummed = Web3.to_checksum_address(address)
            return await asyncio.to_thread(w3.eth.get_balance, checksummed)
        except Exception as e:
            raise RPCError("Failed to fetch balance") from e

    async def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        """Fetch transaction receipt if mined."""
        settings = get_settings()
        if settings.execution_mode == "simulated":
            return None  # Simulation never fabricates a mined receipt.

        try:
            w3 = self._get_w3()
            if await asyncio.to_thread(lambda: w3.eth.chain_id) != self._chain_id:
                raise RPCError("RPC chain identity mismatch")
            receipt = await asyncio.to_thread(w3.eth.get_transaction_receipt, tx_hash)
            if receipt is None:
                return None
            normalized = json.loads(Web3.to_json(receipt))
            normalized["transactionHash"] = "0x" + receipt["transactionHash"].hex().removeprefix(
                "0x"
            )
            return normalized
        except Exception:
            logger.warning("Receipt unavailable; no confirmation asserted")
            return None
