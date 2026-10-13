"""
KiteShield Wallet — Database Seeder Script

Seeds initial policies, sample proposals, and verifiable audit records
for development and live demonstration.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from app.db import get_session_factory, init_db
from app.models import (
    ApprovalRequest,
    Policy,
    PolicyDecision,
    Proposal,
    Transaction,
    utc_now_str,
)
from app.services.audit import AuditService

audit_service = AuditService()


async def seed() -> None:
    print("Initializing database tables...")
    await init_db()

    session_factory = get_session_factory()
    async with session_factory() as session:
        # Check if policy exists
        from sqlalchemy import select
        res = await session.execute(select(Policy).limit(1))
        if res.scalar_one_or_none():
            print("Database already seeded. Skipping.")
            return

        print("Seeding baseline policy (v1)...")
        now_str = utc_now_str()
        allowed_addrs = [
            "0x742d35cc6634c0532925a3b844bc9e7595f2bd1e",
            "0x5555555555555555555555555555555555555555",
            "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
        ]
        blocked_addrs = [
            "0xdead00000000000000000000000000000000dead",
        ]
        baseline_policy = Policy(
            version=1,
            max_amount_wei="1000000000000000000",  # 1.0 ETH
            daily_limit_wei="5000000000000000000",  # 5.0 ETH
            allowed_recipients=json.dumps(allowed_addrs),
            blocked_recipients=json.dumps(blocked_addrs),
            escalation_threshold_wei="100000000000000000",  # 0.1 ETH
            is_active=True,
            created_at=now_str,
        )
        session.add(baseline_policy)
        await session.flush()

        await audit_service.record_event(
            session=session,
            event_type="POLICY_CREATED",
            correlation_id="genesis-policy-setup",
            actor="system:genesis",
            details={
                "policy_version": 1,
                "max_amount_wei": baseline_policy.max_amount_wei,
                "escalation_threshold_wei": baseline_policy.escalation_threshold_wei,
            },
            policy_version=1,
        )

        print("Seeding sample proposals...")
        # 1. ALLOWED & SUBMITTED proposal
        p1 = Proposal(
            correlation_id="demo-prop-1",
            agent_prompt="Send 0.05 ETH to community grant address",
            recipient="0x742d35cc6634c0532925a3b844bc9e7595f2bd1e",
            amount_wei="50000000000000000",  # 0.05 ETH
            chain_id=11155111,
            asset_type="NATIVE_ETH",
            status="SUBMITTED",
            created_at=now_str,
            updated_at=now_str,
        )
        session.add(p1)
        await session.flush()

        d1 = PolicyDecision(
            proposal_id=p1.id,
            decision="ALLOW",
            reason_codes=json.dumps(["RECIPIENT_IN_ALLOWLIST", "AMOUNT_WITHIN_LIMIT"]),
            policy_version=1,
            evaluated_at=now_str,
        )
        session.add(d1)

        t1 = Transaction(
            proposal_id=p1.id,
            tx_hash="0x3f5c71a9b4d8e20984f18372ab59d7e39401bcae9124482098319fbc49012a91",
            status="SUBMITTED",
            created_at=now_str,
            updated_at=now_str,
        )
        session.add(t1)

        await audit_service.record_event(
            session=session,
            event_type="PROPOSAL_CREATED",
            correlation_id=p1.correlation_id,
            actor="agent",
            details={"proposal_id": p1.id, "amount_wei": p1.amount_wei},
        )
        await audit_service.record_event(
            session=session,
            event_type="POLICY_ALLOW",
            correlation_id=p1.correlation_id,
            actor="policy_engine",
            details={"proposal_id": p1.id},
            policy_version=1,
        )
        await audit_service.record_event(
            session=session,
            event_type="TX_SUBMITTED",
            correlation_id=p1.correlation_id,
            actor="blockchain_service",
            details={"proposal_id": p1.id, "tx_hash": t1.tx_hash},
            policy_version=1,
        )

        # 2. ESCALATED proposal (awaiting human decision)
        p2 = Proposal(
            correlation_id="demo-prop-2",
            agent_prompt="Send 0.45 ETH for infrastructure quarterly node sponsorship",
            recipient="0x5555555555555555555555555555555555555555",
            amount_wei="450000000000000000",  # 0.45 ETH
            chain_id=11155111,
            asset_type="NATIVE_ETH",
            status="ESCALATED",
            created_at=now_str,
            updated_at=now_str,
        )
        session.add(p2)
        await session.flush()

        d2 = PolicyDecision(
            proposal_id=p2.id,
            decision="ESCALATE",
            reason_codes=json.dumps(
                ["AMOUNT_EXCEEDS_ESCALATION_THRESHOLD", "RECIPIENT_IN_ALLOWLIST"]
            ),
            policy_version=1,
            evaluated_at=now_str,
        )
        session.add(d2)

        exp2 = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
        app2 = ApprovalRequest(
            proposal_id=p2.id,
            action_digest="11155111:NATIVE_ETH:0x5555555555555555555555555555555555555555:450000000000000000",
            status="PENDING",
            expires_at=exp2,
            created_at=now_str,
        )
        session.add(app2)

        await audit_service.record_event(
            session=session,
            event_type="PROPOSAL_CREATED",
            correlation_id=p2.correlation_id,
            actor="agent",
            details={"proposal_id": p2.id, "amount_wei": p2.amount_wei},
        )
        await audit_service.record_event(
            session=session,
            event_type="POLICY_ESCALATE",
            correlation_id=p2.correlation_id,
            actor="policy_engine",
            details={"proposal_id": p2.id, "approval_id": app2.id},
            policy_version=1,
        )

        # 3. BLOCKED proposal (exceeds max limit)
        p3 = Proposal(
            correlation_id="demo-prop-3",
            agent_prompt="Send 3.5 ETH for emergency liquidity rebalancing",
            recipient="0x742d35cc6634c0532925a3b844bc9e7595f2bd1e",
            amount_wei="3500000000000000000",  # 3.5 ETH
            chain_id=11155111,
            asset_type="NATIVE_ETH",
            status="BLOCKED",
            created_at=now_str,
            updated_at=now_str,
        )
        session.add(p3)
        await session.flush()

        d3 = PolicyDecision(
            proposal_id=p3.id,
            decision="BLOCK",
            reason_codes=json.dumps(["AMOUNT_EXCEEDS_LIMIT"]),
            policy_version=1,
            evaluated_at=now_str,
        )
        session.add(d3)

        await audit_service.record_event(
            session=session,
            event_type="PROPOSAL_CREATED",
            correlation_id=p3.correlation_id,
            actor="agent",
            details={"proposal_id": p3.id, "amount_wei": p3.amount_wei},
        )
        await audit_service.record_event(
            session=session,
            event_type="POLICY_BLOCK",
            correlation_id=p3.correlation_id,
            actor="policy_engine",
            details={"proposal_id": p3.id, "reason": "AMOUNT_EXCEEDS_LIMIT"},
            policy_version=1,
        )

        await session.commit()
        print("Database seeding completed successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
