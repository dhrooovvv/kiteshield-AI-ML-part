"""Standing-mandate orchestration. No alternative signer or broadcast pipeline.

Monitoring releases its durable claim transaction before RPC. Proposal initiation
and action-slot consumption are committed together under the existing SQLite lock.
"""

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta

from eth_account import Account
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.exceptions import SigningRejectedError, ValidationError
from app.models import (
    ExecutionAttempt,
    Policy,
    PolicyDecision,
    Proposal,
    TreasuryAction,
    TreasuryMandate,
    generate_uuid,
    utc_now_str,
)
from app.schemas import NormalizedAction
from app.schemas.treasury import MandateInput
from app.services.audit import AuditService
from app.services.blockchain import BlockchainService
from app.services.emergency_stop import EmergencyStopService
from app.services.execution_lock import lock_execution
from app.services.policy_engine import PolicyConfig, PolicyEngine
from app.services.treasury_planner import PlanInput, PlanState, TreasuryPlan, plan_sweep

ACTOR = "treasury_autopilot"
UNRESOLVED = ("PROPOSED", "ALLOWED", "ESCALATED", "APPROVED", "SIGNING", "SIGNED", "SUBMITTED")
PENDING = ("PREPARED", "SIGNED", "UNCERTAIN", "SUBMITTED")


def now() -> datetime:
    return datetime.now(UTC)


def sender_address() -> str:
    return Account.from_key(get_settings().signer_private_key).address


def availability() -> dict:
    s = get_settings()
    reason = (
        "MONITOR_DISABLED"
        if not s.treasury_monitor_enabled
        else "GLOBAL_AUTOMATION_DISABLED"
        if not s.auto_execute_enabled
        else "LIVE_SEPOLIA_REQUIRED"
        if s.execution_mode != "sepolia" or s.chain_id != 11155111
        else None
    )
    return {
        "available": reason is None,
        "reason": reason,
        "integration": "existing_coordinator",
        "monitor_enabled": s.treasury_monitor_enabled,
        "execution_mode": s.execution_mode,
    }


def configured(m: TreasuryMandate) -> dict:
    return json.loads(m.config_json)


def fresh(snapshot: dict, seconds: int) -> bool:
    try:
        age = (now() - datetime.fromisoformat(snapshot["observed_at"])).total_seconds()
        block_age = (now() - datetime.fromisoformat(snapshot["block_time"])).total_seconds()
        return 0 <= age <= seconds and -15 <= block_age <= seconds
    except (KeyError, TypeError, ValueError):
        return False


async def observe(config: dict, factory) -> dict:
    """Read-only pinned-block balance, plus the existing bounded fee preflight.

    No DB session is open during the network snapshot. Fee preflight uses only a
    read session (no SQLite write lock), closed before the observation is returned.
    """
    observed_at = utc_now_str()
    blockchain = BlockchainService()
    try:
        if config["sender"].lower() != sender_address().lower():
            return {"status": "unavailable", "reason": "SENDER_CHANGED", "observed_at": observed_at}

        def read():
            w3 = blockchain._get_w3()
            if w3.eth.chain_id != 11155111:
                raise ValueError("Wrong chain")
            block = w3.eth.get_block("latest")
            number, timestamp = block["number"], block["timestamp"]
            if type(number) is not int or type(timestamp) is not int or min(number, timestamp) < 0:
                raise ValueError("Malformed block quantities")
            block_hash = "0x" + bytes(block["hash"]).hex()
            if not re.fullmatch(r"0x[0-9a-f]{64}", block_hash):
                raise ValueError("Missing block hash")
            balance = w3.eth.get_balance(config["sender"], number)
            if type(balance) is not int or balance < 0 or w3.eth.chain_id != 11155111:
                raise ValueError("Invalid network observation")
            return {
                "status": "available",
                "chain_id": 11155111,
                "sender": config["sender"],
                "balance_wei": str(balance),
                "block_number": number,
                "block_hash": block_hash,
                "block_time": datetime.fromtimestamp(timestamp, UTC).isoformat(),
                "observed_at": observed_at,
                "simulation": get_settings().execution_mode == "simulated",
            }

        snapshot = await asyncio.wait_for(asyncio.to_thread(read), timeout=15)
        candidate = min(
            int(config["sweep_maximum_wei"]),
            max(0, int(snapshot["balance_wei"]) - int(config["target_balance_wei"])),
        )
        if candidate <= 0:
            snapshot["maximum_fee_reserve_wei"] = str(
                get_settings().max_gas_units * get_settings().max_fee_per_gas_wei
            )
            return snapshot
        action = NormalizedAction(
            proposal_id="treasury-read-only-preview",
            correlation_id=generate_uuid(),
            recipient=config["recipient"],
            amount_wei=candidate,
            chain_id=11155111,
        )
        try:
            async with factory() as read_session:
                envelope = await asyncio.wait_for(
                    blockchain.prepare_transaction(read_session, config["sender"], action),
                    timeout=20,
                )
            snapshot["fee_quote"] = {
                key: str(value)
                if key in ("value", "maxFeePerGas", "maxPriorityFeePerGas")
                else value
                for key, value in envelope.items()
            }
            snapshot["maximum_fee_reserve_wei"] = str(envelope["gas"] * envelope["maxFeePerGas"])
        except Exception:
            snapshot["fee_error"] = "BOUNDED_FEE_ESTIMATE_UNAVAILABLE"
            snapshot["maximum_fee_reserve_wei"] = str(
                get_settings().max_gas_units * get_settings().max_fee_per_gas_wei
            )
        return snapshot
    except Exception:
        # RPC errors may embed provider credentials; expose only a stable code.
        return {
            "status": "unavailable",
            "reason": "NETWORK_VERIFICATION_UNAVAILABLE",
            "observed_at": observed_at,
        }


async def history_limits(session, config: dict, exclude: str | None = None) -> tuple[int, bool]:
    rows = (
        await session.scalars(
            select(TreasuryAction).where(TreasuryAction.initiated_at.is_not(None))
        )
    ).all()
    rows = [r for r in rows if r.id != exclude]
    today = now().date().isoformat()
    used = sum(r.initiated_at[:10] == today for r in rows)
    latest = max((r.initiated_at for r in rows), default=None)
    # History is global for the configured signer; edits never reset it.
    cooldown = bool(
        latest
        and (now() - datetime.fromisoformat(latest)).total_seconds() < config["cooldown_seconds"]
    )
    return used, cooldown


async def outstanding(session, exclude_proposal: str | None = None) -> bool:
    attempt = await session.scalar(
        select(ExecutionAttempt.id)
        .where(
            ExecutionAttempt.status.in_(PENDING),
            ExecutionAttempt.proposal_id != (exclude_proposal or ""),
        )
        .limit(1)
    )
    proposal = await session.scalar(
        select(Proposal.id)
        .join(TreasuryAction, TreasuryAction.proposal_id == Proposal.id)
        .where(Proposal.status.in_(UNRESOLVED), Proposal.id != (exclude_proposal or ""))
        .limit(1)
    )
    return bool(attempt or proposal)


async def policy_allows(session, config: dict, amount: int, proposal_id: str = "preview"):
    from app.services.authorization import spending_total

    policy = await session.scalar(
        select(Policy).where(Policy.is_active.is_(True)).order_by(Policy.version.desc()).limit(1)
    )
    if not policy:
        return None, None, False
    pc = PolicyConfig.from_db_row(policy)
    action = NormalizedAction(
        proposal_id=proposal_id,
        correlation_id="treasury-policy",
        recipient=config["recipient"],
        amount_wei=max(1, amount),
        chain_id=11155111,
    )
    decision = PolicyEngine().evaluate(action, pc, await spending_total(session, proposal_id))
    allowed = (
        decision.decision.value == "ALLOW"
        and bool(pc.allowed_recipients)
        and config["recipient"].lower() in pc.allowed_recipients
        and pc.escalation_threshold_wei is not None
        and 0 < amount < pc.escalation_threshold_wei
        and amount <= int(get_settings().auto_execute_max_eth * 10**18)
    )
    return policy, decision, allowed


async def compute_plan(session, m, snapshot):
    c = configured(m)
    used, cooldown = await history_limits(session, c)
    excess = (
        int(snapshot.get("balance_wei", "0"))
        - int(c["target_balance_wei"])
        - int(snapshot.get("maximum_fee_reserve_wei", "0"))
    )
    amount = min(max(0, excess), int(c["sweep_maximum_wei"]))
    _, _, allowed = await policy_allows(session, c, amount)
    stop = await EmergencyStopService().read_state(session)
    valid = c["sender"].lower() == sender_address().lower()
    if (
        m.enabled
        and valid
        and snapshot.get("status") == "available"
        and fresh(snapshot, c["freshness_seconds"])
        and snapshot.get("fee_error")
        and int(snapshot["balance_wei"]) >= int(c["target_balance_wei"])
    ):
        return TreasuryPlan(PlanState.POLICY, "BOUNDED_FEE_ESTIMATE_UNAVAILABLE")
    return plan_sweep(
        PlanInput(
            balance=int(snapshot["balance_wei"]) if snapshot.get("status") == "available" else None,
            target=int(c["target_balance_wei"]),
            sweep_maximum=int(c["sweep_maximum_wei"]),
            minimum_excess=int(c["minimum_excess_wei"]),
            maximum_fee_reserve=int(snapshot.get("maximum_fee_reserve_wei", "0")),
            enabled=m.enabled,
            valid=valid,
            verified=snapshot.get("status") == "available",
            fresh=fresh(snapshot, c["freshness_seconds"]),
            outstanding=await outstanding(session),
            cooldown=cooldown,
            daily_limit_reached=used >= c["daily_action_limit"],
            policy_allowed=allowed and not stop.active and not snapshot.get("fee_error"),
            execution_available=availability()["available"],
            execute_mode=m.mode == "execute",
        )
    )


async def record(session, event: str, cid: str, details: dict, actor=ACTOR):
    await AuditService().record_event(
        session, event_type=event, correlation_id=cid, actor=actor, details=details
    )


async def save_mandate(session, request: MandateInput, actor: str):
    await lock_execution(session)
    m = await session.get(TreasuryMandate, "global", populate_existing=True)
    if request.expected_version != (m.version if m else 0):
        raise ValidationError("MANDATE_VERSION_CONFLICT: refresh before changing the mandate")
    c = request.model_dump(exclude={"expected_version"})
    if c["sender"].lower() != sender_address().lower():
        raise ValidationError("Mandate sender must match the configured signer public address")
    _, _, allowed = await policy_allows(session, c, int(c["sweep_maximum_wei"]))
    if not allowed:
        raise ValidationError("POLICY_RESTRICTED: mandate maximum must fit unattended policy scope")
    if m is None:
        m = TreasuryMandate(
            id="global",
            version=1,
            config_json=json.dumps(c),
            enabled=False,
            mode="plan_only",
            created_by=actor,
            updated_by=actor,
        )
        session.add(m)
        event = "TREASURY_MANDATE_CREATED"
    else:
        m.version += 1
        m.config_json, m.enabled, m.mode = json.dumps(c), False, "plan_only"
        m.updated_by, m.updated_at = actor, utc_now_str()
        m.claim_token = m.claim_until = None
        m.observation_json = m.last_state = m.last_plan_json = None
        event = "TREASURY_MANDATE_UPDATED"
    await session.flush()
    await record(
        session, event, m.id, {"mandate_id": m.id, "version": m.version, "config": c}, actor
    )
    return m


async def change_mode(session, request, actor):
    await lock_execution(session)
    m = await session.get(TreasuryMandate, "global", populate_existing=True)
    if not m or m.version != request.expected_version:
        raise ValidationError("MANDATE_VERSION_CONFLICT: refresh the mandate")
    if request.mode == "execute":
        if not m.enabled or m.mode != "plan_only" or not m.observation_json:
            raise ValidationError("Enable plan-only and observe before granting execute permission")
        if not request.confirm_standing_permission or not availability()["available"]:
            raise ValidationError(
                "EXECUTION_UNAVAILABLE: explicit standing permission and global flags required"
            )
        plan = await compute_plan(session, m, json.loads(m.observation_json))
        if plan.state != PlanState.ELIGIBLE:
            raise ValidationError("Fresh eligible plan required before execute activation")
    m.version += 1
    m.enabled = request.mode != "off"
    m.mode = "execute" if request.mode == "execute" else "plan_only"
    m.updated_by, m.updated_at = actor, utc_now_str()
    m.claim_token = m.claim_until = None
    await record(
        session, "TREASURY_MODE_CHANGED", m.id, {"version": m.version, "mode": request.mode}, actor
    )
    return m


async def tick(factory, *, plan_only: bool = False):
    """One bounded monitoring pass. Manual observation always forces plan-only."""
    token = generate_uuid()
    async with factory() as session:
        await lock_execution(session)
        m = await session.get(TreasuryMandate, "global", populate_existing=True)
        if not m or not m.enabled:
            return
        if m.claim_until and datetime.fromisoformat(m.claim_until) > now():
            return
        m.claim_token = token
        m.claim_until = (
            now() + timedelta(seconds=get_settings().treasury_claim_seconds)
        ).isoformat()
        version, config = m.version, configured(m)
        await session.commit()
    snapshot = await observe(config, factory)
    proposal_id = None
    async with factory() as session:
        await lock_execution(session)
        m = await session.get(TreasuryMandate, "global", populate_existing=True)
        if not m or m.version != version or m.claim_token != token or not m.enabled:
            return
        if datetime.fromisoformat(m.claim_until) <= now():
            return
        plan = await compute_plan(session, m, snapshot)
        m.observation_json = json.dumps(snapshot)
        plan_json = json.dumps(plan.to_dict())
        previous = json.loads(m.last_plan_json) if m.last_plan_json else {}
        changed = any(
            previous.get(key) != plan.to_dict()[key]
            for key in ("state", "reason", "proposed_amount_wei")
        )
        m.last_state = plan.state.value
        m.last_plan_json = plan_json
        m.claim_token = m.claim_until = None
        initiate = (
            not plan_only
            and m.mode == "execute"
            and plan.state == PlanState.ELIGIBLE
            and availability()["available"]
        )
        if changed or initiate:
            action = TreasuryAction(
                mandate_id=m.id,
                mandate_version=version,
                config_json=m.config_json,
                observation_json=json.dumps(snapshot),
                plan_json=json.dumps(plan.to_dict()),
                state=plan.state.value,
                reason=plan.reason,
                claim_token=token,
            )
            session.add(action)
            await session.flush()
            await record(
                session,
                "TREASURY_PLAN",
                action.id,
                {
                    "mandate_version": version,
                    "state": plan.state.value,
                    "block_number": snapshot.get("block_number"),
                    **plan.to_dict(),
                },
            )
            if initiate:
                proposal = Proposal(
                    correlation_id=action.id,
                    agent_prompt="Treasury sweep · deterministic standing mandate",
                    recipient=config["recipient"],
                    amount_wei=plan.proposed_amount_wei,
                    chain_id=11155111,
                    status="ALLOWED",
                )
                session.add(proposal)
                await session.flush()
                canonical = NormalizedAction(
                    proposal_id=proposal.id,
                    correlation_id=proposal.correlation_id,
                    recipient=proposal.recipient,
                    amount_wei=int(proposal.amount_wei),
                    chain_id=11155111,
                )
                policy, decision, allowed = await policy_allows(
                    session, config, canonical.amount_wei, proposal.id
                )
                if not allowed:
                    raise SigningRejectedError("Current policy restricted treasury initiation")
                session.add(
                    PolicyDecision(
                        proposal_id=proposal.id,
                        decision="ALLOW",
                        policy_version=policy.version,
                        reason_codes=json.dumps(decision.reason_codes),
                        action_digest=canonical.action_digest_without_nonce(),
                    )
                )
                action.proposal_id = proposal.id
                action.action_digest = canonical.action_digest_without_nonce()
                action.initiated_at, action.state = utc_now_str(), "INITIATED"
                proposal_id = proposal.id
                await record(
                    session,
                    "TREASURY_PROPOSAL_INITIATED",
                    action.id,
                    {
                        "proposal_id": proposal.id,
                        "mandate_version": version,
                        "provenance": "DETERMINISTIC_MANDATE",
                        "screening": "NOT_APPLICABLE",
                    },
                )
        await session.commit()
    if proposal_id:
        await run_execution(factory, proposal_id)


async def run_execution(factory, proposal_id):
    # Import existing service instances only when needed; no credential use.
    from app.api.routes.proposals import (
        audit_service,
        blockchain_service,
        capability_service,
        isolated_signer,
    )
    from app.services.execution import execute_payment

    async with factory() as session:
        try:
            await execute_payment(
                session,
                proposal_id,
                capability_service,
                isolated_signer,
                blockchain_service,
                audit_service,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            # Signed/uncertain records may have been committed by the coordinator.
            await lock_execution(session)
            action = await session.scalar(
                select(TreasuryAction).where(TreasuryAction.proposal_id == proposal_id)
            )
            action.state, action.reason = "DEFERRED", "EXECUTION_REQUIRES_RECONCILIATION"
            await record(
                session,
                "TREASURY_EXECUTION_DEFERRED",
                action.id,
                {"proposal_id": proposal_id, "reason": action.reason},
            )
            await session.commit()


async def prepare_authority_context(session, proposal_id):
    """Coordinator preflight before the execution lock and fresh signing authority.

    Runtime-only proof cannot be supplied through the API or a capability claim.
    Signed attempts skip mandate invalidation, retaining existing recovery checks.
    """
    row = await session.scalar(
        select(TreasuryAction).where(TreasuryAction.proposal_id == proposal_id)
    )
    if row is None:
        return
    attempt = await session.scalar(
        select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == proposal_id)
    )
    if attempt and attempt.raw_transaction:
        return
    config, version = json.loads(row.config_json), row.mandate_version
    epoch = await execution_epoch(session, proposal_id)
    # Treasury initiation is already durable. Do not hold the coordinator's DB
    # transaction across fresh RPC; the locked authorization gate rereads state.
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    snapshot = await observe(config, factory)
    session.info["treasury_authority"] = {
        "proposal_id": proposal_id,
        "version": version,
        "snapshot": snapshot,
        "execution_epoch": epoch,
    }


async def execution_epoch(session, proposal_id):
    """Detect competing wallet executions between observation and lock acquisition.

    A completed competing payment is just as important as an outstanding one:
    its balance change must not be authorized against an earlier snapshot.
    """
    from app.models import SpendingRecord

    attempts = (
        await session.execute(
            select(ExecutionAttempt.id, ExecutionAttempt.status, ExecutionAttempt.tx_hash)
            .where(ExecutionAttempt.proposal_id != proposal_id)
            .order_by(ExecutionAttempt.id)
        )
    ).all()
    spending = (
        await session.execute(
            select(
                SpendingRecord.id,
                SpendingRecord.status,
                SpendingRecord.amount_wei,
                SpendingRecord.period_date,
            )
            .where(SpendingRecord.proposal_id != proposal_id)
            .order_by(SpendingRecord.id)
        )
    ).all()
    return tuple(tuple(row) for row in attempts), tuple(tuple(row) for row in spending)


async def validate_mandate_authority(session, action):
    row = await session.scalar(
        select(TreasuryAction)
        .where(TreasuryAction.proposal_id == action.proposal_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        return
    attempt = await session.scalar(
        select(ExecutionAttempt)
        .where(ExecutionAttempt.proposal_id == action.proposal_id)
        .execution_options(populate_existing=True)
    )
    if attempt and attempt.raw_transaction:
        # Disabling cannot unsign a transaction; no fresh signing on this path.
        return
    m = await session.get(TreasuryMandate, "global", populate_existing=True)
    context = session.info.get("treasury_authority", {})
    c = json.loads(row.config_json)
    snapshot = context.get("snapshot", {})
    if (
        not m
        or not m.enabled
        or m.mode != "execute"
        or m.version != row.mandate_version
        or m.config_json != row.config_json
        or not availability()["available"]
        or context.get("proposal_id") != action.proposal_id
        or context.get("version") != m.version
        or row.action_digest != action.action_digest_without_nonce()
        or c["sender"].lower() != sender_address().lower()
        or c["recipient"].lower() != action.recipient.lower()
        or action.chain_id != 11155111
        or snapshot.get("status") != "available"
        or snapshot.get("fee_error")
        or snapshot.get("chain_id") != 11155111
        or not fresh(snapshot, c["freshness_seconds"])
        or context.get("execution_epoch") != await execution_epoch(session, action.proposal_id)
    ):
        raise SigningRejectedError(
            "Treasury mandate invalidated or fresh monitoring authority unavailable"
        )
    used, cooldown = await history_limits(session, c, exclude=row.id)
    reserve = int(snapshot["maximum_fee_reserve_wei"])
    excess = int(snapshot["balance_wei"]) - int(c["target_balance_wei"]) - reserve
    _, _, allowed = await policy_allows(session, c, action.amount_wei, action.proposal_id)
    envelope_cost = 0
    if attempt:
        envelope = json.loads(attempt.envelope)
        envelope_cost = envelope["gas"] * envelope["maxFeePerGas"]
    if (
        cooldown
        or used >= c["daily_action_limit"]
        or not row.initiated_at
        or not allowed
        or await outstanding(session, action.proposal_id)
        or action.amount_wei > min(excess, int(c["sweep_maximum_wei"]))
        or excess < int(c["minimum_excess_wei"])
        or envelope_cost > reserve
    ):
        raise SigningRejectedError(
            "Treasury budget, scope, fees, cooldown or outstanding action prevents execution"
        )


async def monitor(factory):
    while True:
        try:
            await tick(factory)
            await reconcile_outstanding(factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            # No provider errors or credentials in logs. A durable state remains.
            from app.core.logging import get_logger

            get_logger("treasury").warning(
                "Treasury monitor pass unavailable; no new authority inferred"
            )
        await asyncio.sleep(get_settings().treasury_monitor_interval_seconds)


async def reconcile_outstanding(factory):
    """Read receipts only. Never automatic re-signing, fee bumping or re-broadcast."""
    from app.models import Transaction
    from app.services.receipt import reconcile_receipt

    async with factory() as session:
        candidates = (
            await session.execute(
                select(TreasuryAction.id, Transaction.id, Transaction.tx_hash)
                .join(Transaction, Transaction.proposal_id == TreasuryAction.proposal_id)
                .where(TreasuryAction.state.not_in(("CONFIRMED", "REVERTED", "SIMULATED")))
                .order_by(TreasuryAction.created_at)
                .limit(10)
            )
        ).all()
    for action_id, tx_id, tx_hash in candidates:
        # Fetch outside a DB transaction, then pass that receipt to the existing
        # validator. This adapter can only return the one read receipt.
        receipt = await BlockchainService().get_transaction_receipt(tx_hash)

        class ObservedReceipt:
            def __init__(self, expected_hash, observed_receipt):
                self.expected_hash = expected_hash
                self.observed_receipt = observed_receipt

            async def get_transaction_receipt(self, requested_hash):
                if requested_hash != self.expected_hash:
                    raise SigningRejectedError("Receipt identity changed")
                return self.observed_receipt

        async with factory() as session:
            row = await session.get(TreasuryAction, action_id)
            tx = await session.get(Transaction, tx_id)
            await reconcile_receipt(session, tx, ObservedReceipt(tx_hash, receipt))
            state = tx.execution_outcome or tx.status
            if row.state != state:
                row.state, row.updated_at = state, utc_now_str()
                await record(
                    session,
                    "TREASURY_EXECUTION_STATUS",
                    row.id,
                    {"proposal_id": row.proposal_id, "state": state, "tx_hash": tx.tx_hash},
                )
            await session.commit()
