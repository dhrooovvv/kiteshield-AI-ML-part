"""Persist genuine authorization context for capability/signer unit tests."""

import json
from datetime import UTC, datetime, timedelta

from eth_account import Account
from sqlalchemy import select

from app.core.config import get_settings
from app.models import (
    ApprovalRequest,
    ExecutionAttempt,
    Policy,
    PolicyDecision,
    Proposal,
    SpendingRecord,
)
from app.services.blockchain import BlockchainService


async def seed_authorization(session, action, approval_id=None):
    policy = await session.scalar(select(Policy).where(Policy.version == 1))
    if policy is None:
        policy = Policy(version=1, max_amount_wei=str(10**24), is_active=True)
        session.add(policy)
    if approval_id:
        policy.escalation_threshold_wei = "1"
    proposal = await session.get(Proposal, action.proposal_id)
    if proposal is None:
        proposal = Proposal(
            id=action.proposal_id,
            correlation_id=action.correlation_id,
            agent_prompt="Explicit test payment",
            recipient=action.recipient,
            amount_wei=str(action.amount_wei),
            chain_id=action.chain_id,
        )
        session.add(proposal)
    proposal.status = "APPROVED" if approval_id else "ALLOWED"
    decision = await session.scalar(
        select(PolicyDecision).where(PolicyDecision.proposal_id == action.proposal_id)
    )
    if decision is None:
        decision = PolicyDecision(proposal_id=action.proposal_id, reason_codes="[]")
        session.add(decision)
    decision.decision = "ESCALATE" if approval_id else "ALLOW"
    decision.policy_version = 1
    decision.action_digest = action.action_digest_without_nonce()
    if approval_id and await session.get(ApprovalRequest, approval_id) is None:
        session.add(
            ApprovalRequest(
                id=approval_id,
                proposal_id=action.proposal_id,
                policy_version=1,
                status="APPROVED",
                action_digest=action.action_digest_without_nonce(),
                approved_by="human_approver",
                expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            )
        )
    await session.flush()
    attempt = await session.scalar(
        select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == action.proposal_id)
    )
    if attempt is None:
        sender = Account.from_key(get_settings().signer_private_key).address
        envelope = await BlockchainService().prepare_transaction(session, sender, action)
        attempt = ExecutionAttempt(
            id="execution-" + action.proposal_id,
            proposal_id=action.proposal_id,
            sender=sender.lower(),
            nonce=envelope["nonce"],
            chain_id=action.chain_id,
            policy_version=1,
            approval_id=approval_id,
            envelope=json.dumps(envelope, sort_keys=True, separators=(",", ":")),
            status="PREPARED",
        )
        session.add(attempt)
        session.add(
            SpendingRecord(
                id=attempt.id,
                proposal_id=action.proposal_id,
                amount_wei=str(action.amount_wei),
                status="RESERVED",
                period_date=datetime.now(UTC).date().isoformat(),
            )
        )
    await session.flush()
