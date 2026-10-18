"""Opt-in orchestration only: no signing or financial authority lives here."""

from sqlalchemy import select

from app.core.config import get_settings
from app.models import AutonomousIntent, ExecutionAttempt, Policy
from app.schemas import NormalizedAction
from app.services.execution import execute_payment
from app.services.execution_lock import lock_execution
from app.services.policy_engine import PolicyConfig


async def maybe_execute(session, proposal, verified_rpc, capability, signer, blockchain, audit):
    settings = get_settings()
    if (
        not settings.auto_execute_enabled
        or settings.execution_mode != "sepolia"
        or settings.chain_id != 11155111
        or not isinstance(verified_rpc, dict)
        or verified_rpc.get("chain_id") != 11155111
        or proposal.chain_id != 11155111
        or proposal.status != "ALLOWED"
        or proposal.policy_decision.decision != "ALLOW"
    ):
        return proposal
    await lock_execution(session)
    intent = await session.get(AutonomousIntent, proposal.id)
    action = NormalizedAction(
        proposal_id=proposal.id, correlation_id=proposal.correlation_id,
        recipient=proposal.recipient, amount_wei=int(proposal.amount_wei),
        chain_id=proposal.chain_id,
    )
    if not intent or intent.outcome != "BENIGN" or intent.started or (
        intent.action_digest != action.action_digest_without_nonce()
    ):
        return proposal
    policy = await session.scalar(
        select(Policy).where(Policy.is_active.is_(True)).order_by(Policy.version.desc()).limit(1)
    )
    if not policy or policy.version != proposal.policy_decision.policy_version:
        return proposal
    config = PolicyConfig.from_db_row(policy)
    amount = int(proposal.amount_wei)
    if (
        not config.allowed_recipients
        or proposal.recipient.lower() not in config.allowed_recipients
        or amount <= 0
        or amount > int(settings.auto_execute_max_eth * 10**18)
        or config.escalation_threshold_wei is None
        or amount >= config.escalation_threshold_wei
    ):
        return proposal
    # Serialize outstanding autonomous/manual executions before allocating another nonce.
    pending = await session.scalar(select(ExecutionAttempt.id).where(
        ExecutionAttempt.status.in_(("PREPARED", "SIGNED", "UNCERTAIN", "SUBMITTED"))
    ).limit(1))
    if pending:
        return proposal
    intent.started = True
    proposal_id, correlation_id = proposal.id, proposal.correlation_id
    await audit.record_event(
        session, event_type="AUTO_EXECUTION_START", actor="autonomous_executor",
        correlation_id=proposal.correlation_id, details={"proposal_id": proposal.id},
    )
    try:
        result = await execute_payment(session, proposal.id, capability, signer, blockchain, audit)
    except Exception:
        # The coordinator may already have committed signed bytes. Never replace them.
        await session.rollback()
        intent = await session.get(AutonomousIntent, proposal_id)
        if intent:
            intent.started = True
        await audit.record_event(
            session, event_type="AUTO_EXECUTION_FAILURE", actor="autonomous_executor",
            correlation_id=correlation_id, details={"proposal_id": proposal_id},
        )
        await session.commit()
        raise
    await audit.record_event(
        session, event_type="AUTO_EXECUTION_BROADCAST", actor="autonomous_executor",
        correlation_id=result.correlation_id, details={"proposal_id": result.id},
    )
    return result
