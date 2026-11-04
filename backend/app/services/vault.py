"""Deterministic vault scope. Chain observations never create administrator grants."""

import asyncio
import hashlib
import json
import os
import stat
import time
from pathlib import Path

from eth_account import Account
from sqlalchemy import select
from web3 import Web3

from app.core.config import get_settings
from app.exceptions import SigningRejectedError
from app.models import Policy, Proposal, SpendingRecord, VaultOperation, VaultRegistry
from app.schemas import NormalizedAction
from app.schemas.vault import VaultKind, VaultPayload, VaultPayoutAction


def reject(message):
    raise SigningRejectedError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def artifact():
    settings = get_settings()
    if not settings.vault_enabled:
        reject("Guarded vault is disabled")
    content = (Path(__file__).parents[1] / "contracts" / "guarded_vault.json").read_bytes()
    if hashlib.sha256(content).hexdigest() != settings.vault_artifact_sha256:
        reject("Vault artifact pin mismatch")
    return json.loads(content)


def owner_address():
    return Account.from_key(get_settings().signer_private_key).address


def agent_key():
    """Only the existing signer calls this; no API returns this value."""
    settings = get_settings()
    path = Path(settings.vault_agent_key_file)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            reject("Agent key requires a private owner-controlled regular file")
        content = os.read(fd, 256).decode().strip()
    finally:
        os.close(fd)
    account = Account.from_key(content)
    if (
        account.address.lower() != settings.vault_agent_address.lower()
        or account.address.lower() == owner_address().lower()
    ):
        reject("Agent identity is not the configured distinct agent")
    return content


def runtime_hash(owner):
    value = artifact()
    code = bytearray.fromhex(value["runtime"].removeprefix("0x"))
    word = bytes.fromhex(owner.removeprefix("0x")).rjust(32, b"\0")
    for references in value["immutable_references"].values():
        for reference in references:
            if reference["length"] != 32:
                reject("Unexpected immutable layout")
            start = reference["start"]
            code[start : start + 32] = word
    return "0x" + Web3.keccak(bytes(code)).hex().removeprefix("0x")


async def chain_state(blockchain, registry):
    def read():
        w3 = blockchain._get_w3()
        if w3.eth.chain_id != 11155111:
            reject("Vault RPC must be Sepolia")
        address = Web3.to_checksum_address(registry.address)
        block = w3.eth.get_block("latest")
        number = int(block["number"])
        code = w3.eth.get_code(address, block_identifier=number)
        if "0x" + Web3.keccak(bytes(code)).hex().removeprefix("0x") != registry.runtime_hash:
            reject("On-chain vault code does not match the pinned runtime")
        contract = w3.eth.contract(address=address, abi=artifact()["abi"])
        names = (
            "owner",
            "agent",
            "recipient",
            "remaining",
            "perPayment",
            "expires",
            "nonce",
            "epoch",
            "paused",
        )
        state = {
            name: getattr(contract.functions, name)().call(block_identifier=number)
            for name in names
        }
        state.update(
            block=number,
            timestamp=int(block["timestamp"]),
            balance=w3.eth.get_balance(address, block_identifier=number),
            agent_balance=w3.eth.get_balance(
                Web3.to_checksum_address(registry.agent), block_identifier=number
            ),
        )
        return state

    return await asyncio.to_thread(read)


async def action_for_proposal(session, proposal):
    op = await session.scalar(
        select(VaultOperation).where(VaultOperation.proposal_id == proposal.id)
    )
    fields = dict(
        proposal_id=proposal.id,
        correlation_id=proposal.correlation_id,
        recipient=proposal.recipient,
        amount_wei=int(proposal.amount_wei),
        chain_id=proposal.chain_id,
    )
    if op:
        payload = VaultPayload.model_validate_json(op.payload)
        if payload.kind != VaultKind.PAY or payload.digest() != op.authority_digest:
            reject("Proposal has invalid vault binding")
        return VaultPayoutAction(**fields, operation_id=op.id, vault_digest=payload.digest())
    return NormalizedAction(**fields)


async def validate_operation(session, op, blockchain, *, envelope=False, broadcast=False):
    """Run independently at capability issuance, signing and broadcast."""
    from app.services.authorization import validate_authorization
    from app.services.emergency_stop import EmergencyStopService

    await EmergencyStopService().require_running(session)
    settings = get_settings()
    compiled = artifact()
    if settings.execution_mode != "sepolia" or op.execution_mode != "sepolia":
        reject("Vault integration requires explicit Sepolia mode")
    payload = VaultPayload.model_validate_json(op.payload)
    registry = await session.get(VaultRegistry, "global", populate_existing=True)
    policy = await session.scalar(select(Policy).where(Policy.is_active.is_(True)))
    if (
        not registry
        or not policy
        or policy.version != op.policy_version
        or payload.digest() != op.authority_digest
        or payload.kind.value != op.kind
        or payload.artifact_hash != settings.vault_artifact_sha256
        or registry.owner.lower() != owner_address().lower()
        or registry.agent.lower() != settings.vault_agent_address.lower()
        or registry.runtime_hash != runtime_hash(registry.owner)
        or payload.owner.lower() != registry.owner.lower()
        or payload.agent.lower() != registry.agent.lower()
        or payload.recipient.lower() != settings.autonomy_recipient.lower()
        or registry.owner.lower() == registry.agent.lower()
    ):
        reject("Vault authority, identity, artifact or policy changed")
    expected_sender = registry.agent if payload.agent_operation else registry.owner
    if op.sender != expected_sender.lower():
        reject("Vault sender does not match its typed role")
    if payload.agent_operation:
        if op.authorized_by != "proposer":
            reject("Agent operation lacks proposer intent")
    elif op.authorized_by != "policy_administrator":
        reject("Owner operation lacks administrator intent")
    if payload.kind == VaultKind.PAY:
        if not settings.autonomy_vault_payments_enabled or not op.proposal_id:
            reject("Autonomous vault payments are disabled or unbound")
        proposal = await session.get(Proposal, op.proposal_id, populate_existing=True)
        if not proposal or (proposal.recipient.lower(), int(proposal.amount_wei)) != (
            payload.recipient.lower(),
            payload.amount_wei,
        ):
            reject("Vault payment does not match its business proposal")
        await validate_authorization(
            session, await action_for_proposal(session, proposal), op.policy_version, op.approval_id
        )
    elif op.proposal_id:
        reject("Only a payment can have a payout proposal")
    if payload.kind == VaultKind.DEPLOY:
        if registry.address or payload.vault or payload.epoch:
            reject("A vault is already deployed or the deployment scope is stale")
    else:
        if (
            not registry.address
            or not payload.vault
            or payload.vault.lower() != registry.address.lower()
        ):
            reject("Vault address changed")
        state = await chain_state(blockchain, registry)
        if state["owner"].lower() != registry.owner.lower() or state["epoch"] != payload.epoch:
            reject("Vault owner or epoch changed; administrator review required")
        if payload.epoch != registry.epoch:
            reject("On-chain authority is not the administrator's registered epoch")
        if (
            payload.kind != VaultKind.CONFIGURE
            and registry.configured
            and (
                state["agent"].lower() != payload.agent.lower()
                or state["recipient"].lower() != payload.recipient.lower()
            )
        ):
            reject("Unexpected on-chain session identity")
        if payload.kind == VaultKind.PAY and (
            not registry.configured
            or state["paused"]
            or state["nonce"] != payload.session_nonce
            or state["timestamp"] >= state["expires"]
            or int(time.time()) >= state["expires"]
            or not 0
            < payload.amount_wei
            <= min(state["remaining"], state["perPayment"], state["balance"])
        ):
            reject("Vault session is paused, stale, expired or outside its allowance")
        if payload.kind == VaultKind.TIGHTEN and (
            not registry.configured
            or payload.budget_wei > state["remaining"]
            or payload.per_payment_wei > state["perPayment"]
            or payload.expires > state["expires"]
        ):
            reject("An agent may only tighten its existing grant")
        if payload.kind == VaultKind.CONFIGURE and not (
            0 < payload.per_payment_wei <= payload.budget_wei <= settings.vault_escrow_budget_wei
            and state["timestamp"]
            < payload.expires
            <= state["timestamp"] + settings.vault_session_ttl_seconds
        ):
            reject("Administrator session exceeds configured grant limits")
        if payload.kind == VaultKind.RECOVER and not 0 < payload.amount_wei <= state["balance"]:
            reject("Recovery exceeds escrow")
    others = (await session.scalars(select(VaultOperation).where(VaultOperation.id != op.id))).all()
    for kind, limit in (
        (VaultKind.DEPOSIT, settings.vault_escrow_budget_wei),
        (VaultKind.GAS_FUND, settings.vault_agent_gas_budget_wei),
    ):
        if payload.kind == kind:
            allocated = sum(
                VaultPayload.model_validate_json(row.payload).amount_wei
                for row in others
                if row.kind == kind.value and row.status != "REVERTED"
            )
            if not 0 < payload.amount_wei <= limit - allocated:
                reject("Owner funding exceeds the lifetime configured budget")
    if envelope:
        if not op.envelope or op.nonce is None:
            reject("Missing reserved vault envelope")
        tx = json.loads(op.envelope)
        to, value, data = payload.encode(compiled["bytecode"])
        fields = {
            "value",
            "chainId",
            "nonce",
            "gas",
            "maxFeePerGas",
            "maxPriorityFeePerGas",
            "type",
        }
        expected_fields = fields | {"data"} | ({"to"} if to else set())
        if (
            set(tx) != expected_fields
            or any(type(tx.get(field)) is not int for field in fields)
            or tx.get("to") != to
            or tx.get("value") != value
            or tx.get("data") != data
            or tx.get("chainId") != 11155111
            or tx.get("type") != 2
            or tx.get("nonce") != op.nonce
            or not 21000
            <= tx["gas"]
            <= (
                settings.vault_max_gas_units
                if payload.agent_operation
                else settings.vault_owner_max_gas_units
            )
            or not 0 < tx["maxPriorityFeePerGas"] <= settings.max_priority_fee_per_gas_wei
            or not tx["maxPriorityFeePerGas"] <= tx["maxFeePerGas"] <= settings.max_fee_per_gas_wei
        ):
            reject("Vault envelope violates the exact typed call or fee limits")
        fee_reserved = tx["gas"] * tx["maxFeePerGas"]
        for row in others:
            if row.receipt:
                receipt = json.loads(row.receipt)
                fee_reserved += int(receipt["gasUsed"]) * int(receipt["effectiveGasPrice"])
            elif row.envelope:
                other = json.loads(row.envelope)
                fee_reserved += other["gas"] * other["maxFeePerGas"]
        if fee_reserved > settings.vault_fee_budget_wei:
            reject("Vault operations exceed their cumulative fee budget")
        if payload.kind == VaultKind.PAY:
            reservation = await session.get(SpendingRecord, op.id)
            if (
                not reservation
                or reservation.status != "RESERVED"
                or int(reservation.amount_wei) != payload.amount_wei
            ):
                reject("Vault payout has no matching spending reservation")
        if broadcast and (
            not op.raw_transaction
            or not op.tx_hash
            or Account.recover_transaction(op.raw_transaction).lower() != op.sender
            or "0x"
            + Web3.keccak(bytes.fromhex(op.raw_transaction.removeprefix("0x")))
            .hex()
            .removeprefix("0x")
            != op.tx_hash
        ):
            reject("Signed vault payload has no matching durable owner")
    return payload
