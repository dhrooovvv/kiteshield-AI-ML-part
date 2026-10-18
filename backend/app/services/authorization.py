"""Independent persisted authorization checks, used by issuer and signer."""

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ApprovalRequiredError, PolicyBlockError, SigningRejectedError
from app.models import ApprovalRequest, Policy, PolicyDecision, Proposal, SpendingRecord
from app.schemas import NormalizedAction, PolicyDecisionType
from app.services.policy_engine import PolicyConfig, PolicyEngine


async def spending_total(session: AsyncSession, exclude_proposal: str | None = None) -> int:
    today = datetime.now(UTC).date().isoformat()
    stmt = select(SpendingRecord).where(
        or_(
            SpendingRecord.status == "RESERVED",
            (SpendingRecord.status == "COMMITTED") & (SpendingRecord.period_date == today),
        )
    )
    rows = (await session.scalars(stmt)).all()
    total = 0
    for row in rows:
        if not row.amount_wei.isascii() or not row.amount_wei.isdigit() or int(row.amount_wei) <= 0:
            raise SigningRejectedError("Spending state is invalid; execution halted")
        if row.proposal_id != exclude_proposal:
            total += int(row.amount_wei)
    return total


async def validate_authorization(
    session: AsyncSession,
    action: NormalizedAction,
    policy_version: int,
    approval_id: str | None,
) -> None:
    """Never trust a caller's ALLOW/requires_approval claims."""
    proposal = await session.get(Proposal, action.proposal_id, populate_existing=True)
    policy = await session.scalar(
        select(Policy).where(Policy.is_active.is_(True)).order_by(Policy.version.desc()).limit(1)
    )
    decision = await session.scalar(
        select(PolicyDecision)
        .where(PolicyDecision.proposal_id == action.proposal_id)
        .execution_options(populate_existing=True)
    )
    if not proposal or proposal.status not in ("ALLOWED", "APPROVED", "SIGNING", "SIGNED"):
        raise SigningRejectedError("Proposal is not in an executable state")
    if (
        not policy
        or not decision
        or policy.version != policy_version
        or decision.policy_version != policy_version
        or decision.action_digest != action.action_digest_without_nonce()
    ):
        raise SigningRejectedError("Missing, stale, or parameter-mismatched policy evaluation")
    if (
        proposal.recipient.lower() != action.recipient.lower()
        or int(proposal.amount_wei) != action.amount_wei
        or proposal.chain_id != action.chain_id
        or proposal.asset_type != action.action_type.value
    ):
        raise SigningRejectedError("Action does not match the persisted proposal")
    checked = PolicyEngine().evaluate(
        action, PolicyConfig.from_db_row(policy), await spending_total(session, action.proposal_id)
    )
    if checked.decision == PolicyDecisionType.BLOCK or decision.decision == "BLOCK":
        raise PolicyBlockError("Current policy or aggregate budget denies execution")
    if checked.decision.value != decision.decision:
        raise SigningRejectedError("Policy decision changed; reevaluation required")
    if checked.decision == PolicyDecisionType.ESCALATE:
        approval = (
            await session.get(ApprovalRequest, approval_id, populate_existing=True)
            if approval_id
            else None
        )
        if (
            not approval
            or approval.proposal_id != action.proposal_id
            or approval.status != "APPROVED"
            or approval.policy_version != policy_version
            or approval.action_digest != action.action_digest_without_nonce()
            or datetime.fromisoformat(approval.expires_at) <= datetime.now(UTC)
            or not approval.approved_by
        ):
            raise ApprovalRequiredError(
                "Current action-bound, unexpired human approval is required"
            )
    elif approval_id:
        raise SigningRejectedError("Unexpected approval context")
