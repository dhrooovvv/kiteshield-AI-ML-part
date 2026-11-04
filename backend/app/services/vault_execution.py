"""Durable exact-call execution using KiteShield's existing signer and RPC."""

import asyncio
import json
from datetime import UTC, datetime

from eth_abi import decode
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from web3 import Web3

from app.core.config import get_settings
from app.exceptions import RPCError, SigningRejectedError, TransactionSubmissionError
from app.models import (
    ExecutionAttempt,
    Proposal,
    SpendingRecord,
    Transaction,
    VaultOperation,
    VaultRegistry,
    utc_now_str,
)
from app.schemas.vault import VaultExecutionLimits, VaultKind, VaultPayload
from app.services.execution_lock import lock_execution
from app.services.vault import artifact, canonical, runtime_hash, validate_operation

PENDING = ("PREPARED", "SIGNED", "UNCERTAIN", "SUBMITTED")


async def prepare_operation(session, op, blockchain):
    await lock_execution(session)
    await session.refresh(op)
    if op.status == "PREPARED":
        await validate_operation(session, op, blockchain, envelope=True)
        return json.loads(op.envelope)
    if op.status != "DRAFT":
        raise SigningRejectedError("Vault operation already has a durable execution")
    payload = await validate_operation(session, op, blockchain)
    pending_native = await session.scalar(
        select(ExecutionAttempt.id)
        .where(
            ExecutionAttempt.sender == op.sender,
            or_(
                ExecutionAttempt.execution_mode == "sepolia",
                ExecutionAttempt.execution_mode.is_(None),
            ),
            ExecutionAttempt.status.in_(PENDING),
        )
        .limit(1)
    )
    pending_vault = await session.scalar(
        select(VaultOperation.id)
        .where(
            VaultOperation.id != op.id,
            VaultOperation.sender == op.sender,
            VaultOperation.status.in_(PENDING),
        )
        .limit(1)
    )
    if pending_native or pending_vault:
        raise SigningRejectedError(
            "Reconcile the sender's pending execution before allocating a nonce"
        )
    last_native = await session.scalar(
        select(func.max(ExecutionAttempt.nonce)).where(
            ExecutionAttempt.sender == op.sender, ExecutionAttempt.execution_mode == "sepolia"
        )
    )
    last_vault = await session.scalar(
        select(func.max(VaultOperation.nonce)).where(
            VaultOperation.sender == op.sender, VaultOperation.execution_mode == "sepolia"
        )
    )
    to, value, data = payload.encode(artifact()["bytecode"])
    settings = get_settings()

    def preflight():
        w3 = blockchain._get_w3()
        if w3.eth.chain_id != 11155111:
            raise SigningRejectedError("Vault RPC is not Sepolia")
        sender = Web3.to_checksum_address(op.sender)
        request = dict(from_=sender)  # 'from' is an RPC field, not an authority input.
        request = {"from": request["from_"], "value": value, "data": data}
        if to:
            request["to"] = to
        gas = (int(w3.eth.estimate_gas(request)) * 120 + 99) // 100
        priority = max(1, min(int(w3.eth.max_priority_fee), settings.max_priority_fee_per_gas_wei))
        fee = int(w3.eth.get_block("latest")["baseFeePerGas"]) * 2 + priority
        nonce = max(
            w3.eth.get_transaction_count(sender, "pending"),
            max(
                last_native if last_native is not None else -1,
                last_vault if last_vault is not None else -1,
            )
            + 1,
        )
        gas_limit = (
            settings.vault_max_gas_units
            if payload.agent_operation
            else settings.vault_owner_max_gas_units
        )
        if (
            gas > gas_limit
            or fee > settings.max_fee_per_gas_wei
            or w3.eth.get_balance(sender) < value + gas * fee
        ):
            raise SigningRejectedError("Vault gas, fee or sender balance exceeds its limits")
        result = dict(
            value=value,
            data=data,
            chainId=11155111,
            nonce=nonce,
            gas=gas,
            maxFeePerGas=fee,
            maxPriorityFeePerGas=priority,
            type=2,
        )
        if to:
            result["to"] = to
        return result

    envelope = await asyncio.to_thread(preflight)
    op.envelope, op.nonce, op.status = canonical(envelope), envelope["nonce"], "PREPARED"
    if payload.kind == VaultKind.PAY:
        session.add(
            SpendingRecord(
                id=op.id,
                proposal_id=op.proposal_id,
                amount_wei=str(payload.amount_wei),
                status="RESERVED",
                period_date=datetime.now(UTC).date().isoformat(),
            )
        )
    await session.flush()
    await validate_operation(session, op, blockchain, envelope=True)
    return envelope


async def proposal_with_relations(session, proposal_id):
    return await session.scalar(
        select(Proposal)
        .where(Proposal.id == proposal_id)
        .options(
            selectinload(Proposal.policy_decision),
            selectinload(Proposal.approval_request),
            selectinload(Proposal.transaction),
        )
        .execution_options(populate_existing=True)
    )


async def execute_vault_payment(session, op, capability, signer, blockchain, audit, limits):
    proposal = await proposal_with_relations(session, op.proposal_id)
    if not proposal or not proposal.policy_decision:
        raise SigningRejectedError("Evaluate the vault payout before execution")
    op.policy_version = proposal.policy_decision.policy_version
    op.approval_id = (
        proposal.approval_request.id
        if proposal.policy_decision.decision == "ESCALATE" and proposal.approval_request
        else None
    )
    if not isinstance(limits, VaultExecutionLimits):
        raise SigningRejectedError("Vault payout requires exact typed vault limits")
    await execute_operation(session, op, capability, signer, blockchain, audit, limits)
    return await proposal_with_relations(session, op.proposal_id)


async def execute_operation(session, op, capability, signer, blockchain, audit, limits=None):
    await lock_execution(session)
    await session.refresh(op)
    if op.tx_hash:
        await reconcile_operation(session, op, blockchain, audit)
        # Unknown outcomes never allocate a replacement nonce or sign again.
        return op
    if op.status == "DRAFT":
        await prepare_operation(session, op, blockchain)
    if limits:
        limits.check(op)
    token, claims = await capability.issue_vault_token(session, op, blockchain)
    signed = await signer.sign_vault_operation(session, token, op.id, blockchain)
    op.raw_transaction = signed["raw_transaction"]
    op.tx_hash = "0x" + signed["tx_hash"].removeprefix("0x")
    op.status = "SIGNED"
    if op.proposal_id:
        proposal = await session.get(Proposal, op.proposal_id)
        proposal.status = "SIGNED"
        session.add(
            Transaction(
                proposal_id=proposal.id,
                tx_hash=op.tx_hash,
                status="SIGNED",
                execution_mode="sepolia",
                execution_outcome="SIGNED",
            )
        )
    await audit.record_event(
        session,
        event_type="VAULT_SIGNED",
        correlation_id=op.id,
        actor="logical_signer",
        details={
            "operation_id": op.id,
            "kind": op.kind,
            "payload_digest": op.authority_digest,
            "tx_hash": op.tx_hash,
            "nonce": op.nonce,
            "jti": claims["jti"],
        },
    )
    # Signed bytes, nonce, spending reservation and one-use consumption precede the network.
    await session.commit()
    await lock_execution(session)
    try:
        await validate_operation(session, op, blockchain, envelope=True, broadcast=True)
        w3 = blockchain._get_w3()
        if await asyncio.to_thread(lambda: w3.eth.chain_id) != 11155111:
            raise SigningRejectedError("Broadcast chain mismatch")
        sent = await asyncio.to_thread(
            w3.eth.send_raw_transaction, bytes.fromhex(op.raw_transaction.removeprefix("0x"))
        )
        if "0x" + sent.hex().removeprefix("0x") != op.tx_hash:
            raise TransactionSubmissionError("RPC hash does not match the signed vault operation")
    except Exception as exc:
        op.status = "UNCERTAIN"
        await audit.record_event(
            session,
            event_type="VAULT_UNCERTAIN",
            correlation_id=op.id,
            actor="vault_execution",
            details={"tx_hash": op.tx_hash},
        )
        await session.commit()
        raise TransactionSubmissionError(
            "Vault outcome uncertain; reconcile the same signed operation"
        ) from exc
    op.status = "SUBMITTED"
    if op.proposal_id:
        proposal = await proposal_with_relations(session, op.proposal_id)
        proposal.status = "SUBMITTED"
        proposal.transaction.status = "SUBMITTED"
        proposal.transaction.execution_outcome = "SUBMITTED"
    await audit.record_event(
        session,
        event_type="VAULT_SUBMITTED",
        correlation_id=op.id,
        actor="vault_execution",
        details={"kind": op.kind, "tx_hash": op.tx_hash},
    )
    await session.commit()
    return op


def _hex(value):
    return "0x" + bytes(value).hex()


async def verified_receipt(op, blockchain):
    """Verify the exact transaction, canonical block, pinned code and typed event."""
    payload = VaultPayload.model_validate_json(op.payload)
    envelope = json.loads(op.envelope)

    def read():
        w3 = blockchain._get_w3()
        if w3.eth.chain_id != 11155111:
            raise RPCError("Receipt RPC is not Sepolia")
        from web3.exceptions import TransactionNotFound

        try:
            receipt = w3.eth.get_transaction_receipt(op.tx_hash)
            tx = w3.eth.get_transaction(op.tx_hash)
        except TransactionNotFound:
            return None
        if tx.get("blockHash") is None or tx.get("blockNumber") is None:
            return None
        block = w3.eth.get_block(receipt["blockNumber"])
        if (
            receipt["transactionHash"].hex().removeprefix("0x") != op.tx_hash.removeprefix("0x")
            or tx["hash"] != receipt["transactionHash"]
            or tx["blockHash"] != receipt["blockHash"]
            or tx["blockNumber"] != receipt["blockNumber"]
            or block["hash"] != receipt["blockHash"]
            or tx["from"].lower() != op.sender
            or tx["nonce"] != op.nonce
            or tx.get("to") != envelope.get("to")
            or tx["value"] != envelope["value"]
            or _hex(tx["input"]) != envelope["data"]
            or tx["chainId"] != 11155111
            or tx["gas"] != envelope["gas"]
            or tx["maxFeePerGas"] != envelope["maxFeePerGas"]
            or tx["maxPriorityFeePerGas"] != envelope["maxPriorityFeePerGas"]
            or receipt["status"] not in (0, 1)
            or receipt["gasUsed"] > envelope["gas"]
            or receipt["effectiveGasPrice"] > envelope["maxFeePerGas"]
        ):
            raise RPCError("Vault receipt or transaction does not match its signed envelope")
        if receipt["status"] == 1:
            address = (
                receipt["contractAddress"] if payload.kind == VaultKind.DEPLOY else payload.vault
            )
            if payload.kind == VaultKind.DEPLOY:
                import rlp

                expected = Web3.to_checksum_address(
                    Web3.keccak(rlp.encode([bytes.fromhex(payload.owner[2:]), op.nonce]))[-20:]
                )
                if address != expected:
                    raise RPCError("Deployment address does not match owner and nonce")
            code = w3.eth.get_code(address, block_identifier=receipt["blockNumber"])
            if _hex(Web3.keccak(code)) != runtime_hash(payload.owner):
                raise RPCError("Mined vault runtime does not match the pinned owner and code")
            expected_event = {
                VaultKind.PAY: (
                    "Paid(address,uint256,uint256)",
                    ["uint256", "uint256"],
                    [payload.amount_wei, payload.session_nonce],
                ),
                VaultKind.CONFIGURE: (
                    "SessionConfigured(uint256)",
                    ["uint256"],
                    [payload.epoch + 1],
                ),
                VaultKind.RECOVER: (
                    "Recovered(uint256,uint256)",
                    ["uint256", "uint256"],
                    [payload.amount_wei, payload.epoch + 1],
                ),
                VaultKind.DEPOSIT: ("Deposit(address,uint256)", ["uint256"], [payload.amount_wei]),
                VaultKind.PAUSE: ("Paused()", [], []),
                VaultKind.OWNER_PAUSE: ("Paused()", [], []),
            }.get(payload.kind)
            if expected_event:
                signature, types, values = expected_event
                matches = [
                    log
                    for log in receipt["logs"]
                    if log["address"] == address
                    and log["topics"]
                    and log["topics"][0] == Web3.keccak(text=signature)
                ]
                if len(matches) != 1 or list(decode(types, matches[0]["data"])) != values:
                    raise RPCError("Mined vault event does not prove the typed operation")
                if payload.kind in (VaultKind.PAY, VaultKind.DEPOSIT):
                    indexed = payload.recipient if payload.kind == VaultKind.PAY else payload.owner
                    if len(matches[0]["topics"]) != 2 or bytes(
                        matches[0]["topics"][1]
                    ) != bytes.fromhex(indexed[2:]).rjust(32, b"\0"):
                        raise RPCError("Vault event has the wrong recipient or depositor")
        return json.loads(Web3.to_json(receipt))

    return await asyncio.to_thread(read)


async def reconcile_operation(session, op, blockchain, audit):
    if not op.tx_hash:
        return False
    if op.status in ("CONFIRMED", "REVERTED"):
        observed = await verified_receipt(op, blockchain)
        saved = json.loads(op.receipt) if op.receipt else None
        if (
            not saved
            or not observed
            or any(
                saved[key] != observed[key]
                for key in ("transactionHash", "blockHash", "blockNumber", "status")
            )
        ):
            raise RPCError("Previously confirmed vault receipt is no longer canonical")
        return True
    receipt = await verified_receipt(op, blockchain)
    if receipt is None:
        return False
    await lock_execution(session)
    await session.refresh(op)
    if op.status in ("CONFIRMED", "REVERTED"):
        return True
    success = receipt["status"] == 1
    payload = VaultPayload.model_validate_json(op.payload)
    op.receipt, op.status = canonical(receipt), "CONFIRMED" if success else "REVERTED"
    registry = await session.get(VaultRegistry, "global")
    if success and not op.applied:
        # Only the matching saved administrator request may update registered authority.
        if payload.kind == VaultKind.DEPLOY:
            registry.address = receipt["contractAddress"]
            registry.revision += 1
        elif payload.kind in (VaultKind.CONFIGURE, VaultKind.RECOVER):
            if registry.epoch != payload.epoch:
                raise RPCError("Administrator registry changed while reconciling")
            registry.epoch = payload.epoch + 1
            registry.revision += 1
            registry.configured = payload.kind == VaultKind.CONFIGURE
        op.applied = True
    if op.proposal_id:
        proposal = await proposal_with_relations(session, op.proposal_id)
        tx = proposal.transaction
        if not tx or tx.tx_hash != op.tx_hash:
            raise RPCError("Vault receipt lacks its matching business transaction")
        proposal.status = "CONFIRMED" if success else "TX_FAILED"
        tx.status = "CONFIRMED" if success else "FAILED"
        tx.execution_outcome = op.status
        tx.receipt_json, tx.block_number, tx.gas_used = (
            op.receipt,
            receipt["blockNumber"],
            receipt["gasUsed"],
        )
        tx.error_message = None if success else "On-chain vault call reverted"
        tx.updated_at = utc_now_str()
        reservation = await session.get(SpendingRecord, op.id)
        if not reservation:
            raise RPCError("Vault receipt has no retained spending reservation")
        reservation.status = "COMMITTED" if success else "RELEASED"
        if success:
            reservation.period_date = datetime.now(UTC).date().isoformat()
    await audit.record_event(
        session,
        event_type="VAULT_CONFIRMED" if success else "VAULT_REVERTED",
        correlation_id=op.id,
        actor="vault_receipt_reconciler",
        details={
            "kind": op.kind,
            "tx_hash": op.tx_hash,
            "block_number": receipt["blockNumber"],
            "proposal_id": op.proposal_id,
        },
    )
    await session.flush()
    return True
