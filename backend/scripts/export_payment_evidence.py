"""Export public payment evidence from the existing database; no RPC or signing.

Run from backend: ./.venv/bin/python scripts/export_payment_evidence.py PROPOSAL_ID ...
Raw prompts, credentials, capability tokens and signed transaction bytes are omitted.
"""

import argparse
import asyncio
import json

from sqlalchemy import select

from app.db import get_session_factory
from app.models import AuditEvent, ExecutionAttempt, PolicyDecision, Proposal, Transaction
from app.services.receipt import transaction_response


async def export(proposal_ids: list[str]) -> list[dict]:
    evidence = []
    async with get_session_factory()() as session:
        for proposal_id in proposal_ids:
            proposal = await session.get(Proposal, proposal_id)
            if not proposal:
                raise ValueError("Requested proposal not found")
            tx = await session.scalar(
                select(Transaction).where(Transaction.proposal_id == proposal_id)
            )
            attempt = await session.scalar(
                select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == proposal_id)
            )
            decision = await session.scalar(
                select(PolicyDecision).where(PolicyDecision.proposal_id == proposal_id)
            )
            events = (
                await session.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.correlation_id == proposal.correlation_id)
                    .order_by(AuditEvent.created_at, AuditEvent.id)
                )
            ).all()
            evidence.append(
                {
                    "proposal_id": proposal.id,
                    "correlation_id": proposal.correlation_id,
                    "sender": attempt.sender if attempt else None,
                    "recipient": proposal.recipient,
                    "amount_wei": proposal.amount_wei,
                    "chain_id": proposal.chain_id,
                    "proposal_status": proposal.status,
                    "policy_version": decision.policy_version if decision else None,
                    "policy_decision_id": decision.id if decision else None,
                    "execution_id": attempt.id if attempt else None,
                    "approval_id": attempt.approval_id if attempt else None,
                    "nonce": attempt.nonce if attempt else None,
                    "authorized_envelope": json.loads(attempt.envelope) if attempt else None,
                    "transaction": transaction_response(tx).model_dump() if tx else None,
                    "audit_references": [
                        {
                            "id": event.id,
                            "event_type": event.event_type,
                            "event_hash": event.event_hash,
                            "created_at": event.created_at,
                        }
                        for event in events
                    ],
                    "testnet_acceptance": (
                        "Organizer acceptance of Sepolia evidence remains unconfirmed"
                    ),
                }
            )
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal_ids", nargs="+")
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(export(args.proposal_ids)), indent=2))
    except Exception as exc:
        print(json.dumps({"status": "EXPORT_UNAVAILABLE", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
