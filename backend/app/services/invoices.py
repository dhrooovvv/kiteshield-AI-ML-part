"""Invoice intake and authorization provenance; delegates all execution to the coordinator."""

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import reject_credentials_in_text
from app.exceptions import SigningRejectedError, ValidationError
from app.models import ExecutionAttempt, Policy, PolicyDecision, Proposal
from app.models.invoices import InvoiceEvent, InvoiceRecord, Vendor
from app.schemas import NormalizedAction
from app.schemas.invoices import InvoiceFields, VendorInput, vendor_id_valid
from app.services.amounts import eth_to_wei
from app.services.audit import AuditService
from app.services.authorization import spending_total
from app.services.emergency_stop import EmergencyStopService
from app.services.execution_lock import lock_execution
from app.services.invoice_checks import decision_summary, document_checks, invoice_keys
from app.services.invoice_llm import extract_invoice
from app.services.invoice_screening import enabled as learned_invoice_screening_enabled
from app.services.invoice_screening import invoice_screening, valid_clearance
from app.services.policy_engine import PolicyConfig, PolicyEngine

AUDIT = AuditService()


async def emit(session, record, stage, reason=None):
    record.state, record.reason = stage, reason
    session.add(InvoiceEvent(invoice_id=record.id, stage=stage, reason=reason))
    await AUDIT.record_event(
        session,
        event_type="INVOICE_" + stage,
        actor="invoice_intake",
        correlation_id=record.id,
        details={
            "invoice_id": record.id,
            "document_hash": record.document_hash,
            "proposal_id": record.proposal_id,
            "reason": reason,
        },
    )


async def save_vendor(session, vendor_id, request: VendorInput, actor):
    try:
        vendor_id_valid(vendor_id)
    except ValueError:
        raise ValidationError("INVALID_VENDOR_ID") from None
    await lock_execution(session)
    row = await session.get(Vendor, vendor_id, populate_existing=True)
    if (row.version if row else 0) != request.expected_version:
        raise ValidationError("VENDOR_VERSION_CONFLICT")
    duplicate_name = await session.scalar(
        select(Vendor.id).where(Vendor.name == request.name, Vendor.id != vendor_id)
    )
    if duplicate_name:
        raise ValidationError("VENDOR_NAME_ALREADY_REGISTERED")
    policy = await session.scalar(select(Policy).where(Policy.is_active.is_(True)))
    if not policy:
        raise ValidationError("ACTIVE_POLICY_REQUIRED")
    pc = PolicyConfig.from_db_row(policy)
    if (
        not pc.allowed_recipients
        or request.payout_address.lower() not in pc.allowed_recipients
        or request.payout_address.lower() in (pc.blocked_recipients or [])
    ):
        raise ValidationError("VENDOR_RECIPIENT_MUST_ALREADY_BE_ALLOWLISTED")
    if row is None:
        row = Vendor(id=vendor_id, version=1)
        session.add(row)
    else:
        row.version += 1
    row.name, row.payout_address = request.name, request.payout_address
    row.maximum_wei = str(eth_to_wei(request.maximum_eth))
    row.active, row.updated_by = request.active, actor
    await AUDIT.record_event(
        session,
        event_type="INVOICE_VENDOR_UPDATED",
        correlation_id=vendor_id,
        actor=actor,
        details={"vendor_id": vendor_id, "version": row.version},
    )
    await session.flush()
    return row


async def assess(session, record, fields, *, rules_enabled=True, today=None):
    s = get_settings()
    vendors = list((await session.scalars(select(Vendor))).all())
    vendor, failures = document_checks(
        record.document_text,
        fields,
        vendors,
        today=today or datetime.now(UTC).date(),
        overdue=s.invoice_max_overdue_days,
        future=s.invoice_max_future_days,
        rules_enabled=rules_enabled,
    )
    policy, decision = None, None
    if vendor:
        duplicate, identity = invoice_keys(
            vendor.id, fields.invoice_number, eth_to_wei(fields.amount_eth)
        )
        existing = await session.scalar(
            select(InvoiceRecord.id)
            .where(
                InvoiceRecord.id != record.id,
                (InvoiceRecord.duplicate_key == duplicate)
                | (InvoiceRecord.invoice_identity == identity),
            )
            .limit(1)
        )
        if existing:
            failures.append(("registry", "DUPLICATE_INVOICE"))
        policy = await session.scalar(select(Policy).where(Policy.is_active.is_(True)))
        if not policy:
            failures.append(("policy", "ACTIVE_POLICY_REQUIRED"))
        else:
            action = NormalizedAction(
                proposal_id=record.proposal_id or record.id,
                correlation_id=record.id,
                recipient=vendor.payout_address,
                amount_wei=int(eth_to_wei(fields.amount_eth)),
                chain_id=11155111,
            )
            pc = PolicyConfig.from_db_row(policy)
            decision = PolicyEngine().evaluate(
                action, pc, await spending_total(session, record.proposal_id)
            )
            failures.extend(
                ("policy", reason)
                for reason in decision.reason_codes
                if decision.decision.value != "ALLOW"
            )
            if (
                not pc.allowed_recipients
                or vendor.payout_address.lower() not in pc.allowed_recipients
            ):
                failures.append(("policy", "EXPLICIT_ALLOWLIST_REQUIRED"))
            if action.amount_wei > int(s.auto_execute_max_eth * 10**18):
                failures.append(("policy", "AUTOMATION_CAP_EXCEEDED"))
            if (
                pc.escalation_threshold_wei is None
                or action.amount_wei >= pc.escalation_threshold_wei
            ):
                failures.append(("policy", "BELOW_APPROVAL_THRESHOLD_REQUIRED"))
    if (await EmergencyStopService().read_state(session)).active:
        failures.append(("policy", "EMERGENCY_STOP"))
    return vendor, policy, decision, failures


async def ingest(factory, text, *, content_hash=None, extractor=None, progress=None):
    """Persist claim before model call. Only server code chooses registry payee."""
    if not get_settings().invoice_intake_enabled:
        raise ValidationError("INVOICE_INTAKE_DISABLED")
    if not text or len(text) > 20000:
        raise ValidationError("DOCUMENT_TEXT_SIZE_INVALID")
    reject_credentials_in_text(text)
    digest = content_hash or hashlib.sha256(text.encode()).hexdigest()
    async with factory() as session:
        await lock_execution(session)
        existing = await session.scalar(
            select(InvoiceRecord).where(InvoiceRecord.document_hash == digest)
        )
        if existing:
            return existing.id  # No second extraction, proposal or payment.
        row = InvoiceRecord(
            document_hash=digest,
            document_text=text,
            claim_until=(datetime.now(UTC) + timedelta(seconds=90)).isoformat(),
        )
        session.add(row)
        await session.flush()
        invoice_id = row.id
        await emit(session, row, "OBSERVED", "DOCUMENT_CLAIMED")
        await session.commit()
    return await _process_claim(factory, invoice_id, text, extractor=extractor, progress=progress)


def can_recheck_invoice(row):
    """Only a missing-vendor intake failure with no proposal can be reconsidered."""
    return (
        row.state == "BLOCKED" and row.reason == "EXACT_VENDOR_REQUIRED" and row.proposal_id is None
    )


async def recheck_invoice(factory, invoice_id, actor):
    if not get_settings().invoice_intake_enabled:
        raise ValidationError("INVOICE_INTAKE_DISABLED")
    async with factory() as session:
        await lock_execution(session)
        row = await session.get(InvoiceRecord, invoice_id, populate_existing=True)
        if row is None or not can_recheck_invoice(row):
            raise ValidationError(
                "Only missing-vendor invoices without a proposal can be rechecked"
            )
        if await session.scalar(
            select(Proposal.id).where(Proposal.correlation_id == row.id).limit(1)
        ):
            raise ValidationError(
                "An existing proposal must not be reopened through invoice intake"
            )
        text = row.document_text
        reject_credentials_in_text(text)
        row.claim_until = (datetime.now(UTC) + timedelta(seconds=90)).isoformat()
        await AUDIT.record_event(
            session,
            event_type="INVOICE_RECHECK_REQUESTED",
            actor=actor,
            correlation_id=row.id,
            details={"invoice_id": row.id, "previous_reason": row.reason},
        )
        await emit(session, row, "OBSERVED", "ELIGIBILITY_RECHECK_REQUESTED")
        await session.commit()
    # Reuse screening, extraction, current registry/policy and the existing execution gates.
    # The original record, document hash and event history are retained.
    return await _process_claim(factory, invoice_id, text)


async def _process_claim(factory, invoice_id, text, *, extractor=None, progress=None):
    screening_proof = None
    if learned_invoice_screening_enabled():
        if progress:
            await progress("SCREENING", invoice_id)
        if not get_settings().invoice_learned_evaluated:
            screening_proof = {"classification": "ERROR", "reason": "EVALUATION_REQUIRED"}
        else:
            try:
                screening_proof = await invoice_screening.screen(text)
            except Exception:
                screening_proof = {"classification": "ERROR", "reason": "DETECTOR_UNAVAILABLE"}
        if not isinstance(screening_proof, dict):
            screening_proof = {"classification": "ERROR", "reason": "DETECTOR_OUTPUT_INVALID"}
        classification = screening_proof.get("classification")
        if classification != "BENIGN" or not valid_clearance(screening_proof, text):
            reason = "LEARNED_" + (
                classification if classification in ("ATTACK", "REVIEW", "ERROR") else "ERROR"
            )
            async with factory() as session:
                await lock_execution(session)
                row = await session.get(InvoiceRecord, invoice_id)
                summary = decision_summary([("screening", reason)])
                for counterfactual in summary["without_layer"].values():
                    counterfactual["would_pass_checks"] = None
                summary["counterfactual_scope"] = (
                    "Screening stopped before extraction; downstream checks are unknown"
                )
                summary["screening"] = screening_proof
                row.checks_json = json.dumps(summary)
                await emit(
                    session,
                    row,
                    "BLOCKED" if classification == "ATTACK" else "NEEDS_HUMAN_REVIEW",
                    reason,
                )
                await session.commit()
            return invoice_id
    if progress:
        await progress("EXTRACTING", invoice_id)
    extraction_started = time.monotonic()
    try:
        fields, latency = await (extractor or extract_invoice)(text)
        fields = InvoiceFields.model_validate(fields)
    except asyncio.CancelledError:
        raise
    except Exception:
        async with factory() as session:
            await lock_execution(session)
            row = await session.get(InvoiceRecord, invoice_id)
            row.latency_ms = round((time.monotonic() - extraction_started) * 1000)
            failure_summary = decision_summary([("extraction_validator", "EXTRACTION_INVALID")])
            failure_summary["screening"] = screening_proof
            row.checks_json = json.dumps(failure_summary)
            await emit(session, row, "NEEDS_HUMAN_REVIEW", "MODEL_UNAVAILABLE_OR_INVALID")
            await session.commit()
        return invoice_id
    if progress:
        await progress("VALIDATING", invoice_id)
    async with factory() as session:
        await lock_execution(session)
        row = await session.get(InvoiceRecord, invoice_id, populate_existing=True)
        if row.state != "OBSERVED" or datetime.fromisoformat(row.claim_until) <= datetime.now(UTC):
            await emit(session, row, "NEEDS_HUMAN_REVIEW", "INTAKE_CLAIM_EXPIRED")
            await session.commit()
            return invoice_id
        row.extraction_json = json.dumps(fields.model_dump(), sort_keys=True)
        row.extraction_hash = hashlib.sha256(row.extraction_json.encode()).hexdigest()
        row.latency_ms = latency
        await emit(session, row, "EXTRACTED", "STRICT_SCHEMA_VALID")
        vendor, policy, decision, failures = await assess(session, row, fields)
        if learned_invoice_screening_enabled() and not valid_clearance(screening_proof, text):
            failures.append(("screening", "LEARNED_SCREENING_CONTEXT_CHANGED"))
        summary = decision_summary(failures)
        summary["learned_screening_enabled"] = get_settings().learned_screening_enabled
        summary["invoice_learned_screening_enabled"] = (
            get_settings().invoice_learned_screening_enabled
        )
        summary["learned_screening_evaluated"] = get_settings().invoice_learned_evaluated
        summary["screening"] = screening_proof
        row.checks_json = json.dumps(summary)
        if failures:
            stage = "NEEDS_HUMAN_REVIEW" if failures[0][0] == "extraction_validator" else "BLOCKED"
            await emit(session, row, stage, failures[0][1])
        else:
            row.vendor_id, row.vendor_version = vendor.id, vendor.version
            row.duplicate_key, row.invoice_identity = invoice_keys(
                vendor.id, fields.invoice_number, eth_to_wei(fields.amount_eth)
            )
            proposal = Proposal(
                correlation_id=row.id,
                agent_prompt="Invoice intake · verified vendor registry",
                recipient=vendor.payout_address,
                amount_wei=str(eth_to_wei(fields.amount_eth)),
                chain_id=11155111,
                asset_type="NATIVE_ETH",
                status="ALLOWED",
            )
            session.add(proposal)
            await session.flush()
            action = NormalizedAction(
                proposal_id=proposal.id,
                correlation_id=row.id,
                recipient=vendor.payout_address,
                amount_wei=int(proposal.amount_wei),
                chain_id=11155111,
            )
            row.proposal_id, row.action_digest = proposal.id, action.action_digest_without_nonce()
            session.add(
                PolicyDecision(
                    proposal_id=proposal.id,
                    decision=decision.decision.value,
                    reason_codes=json.dumps(decision.reason_codes),
                    policy_version=policy.version,
                    action_digest=row.action_digest,
                )
            )
            await emit(session, row, "CHECKED", "POLICY_ALLOW_AND_INVOICE_CHECKS_PASSED")
        await session.commit()
    if progress:
        await progress("EXECUTION_CHECK", invoice_id)
    await execute_invoice(factory, invoice_id)
    return invoice_id


async def validate_invoice_authority(session, action):
    """Called independently by the existing issuer, signer and submission gates."""
    row = await session.scalar(
        select(InvoiceRecord)
        .where(InvoiceRecord.proposal_id == action.proposal_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        return
    attempt = await session.scalar(
        select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == action.proposal_id)
    )
    if attempt and attempt.raw_transaction:
        # No fresh signature: permit only the coordinator's existing signed-byte recovery.
        return
    from app.services.invoice_agent import require_not_cancelled

    await require_not_cancelled(session, row.id)
    s = get_settings()
    if (
        not s.invoice_intake_enabled
        or not s.invoice_auto_execute_enabled
        or not s.auto_execute_enabled
    ):
        raise SigningRejectedError("INVOICE_AUTOMATION_DISABLED")
    if s.execution_mode == "sepolia" and not s.invoice_live_execution_enabled:
        raise SigningRejectedError("INVOICE_LIVE_AUTHORIZATION_REQUIRED")
    if row.state not in ("CHECKED", "EXECUTING") or not row.extraction_json:
        raise SigningRejectedError("INVOICE_NOT_EXECUTABLE")
    if hashlib.sha256(row.extraction_json.encode()).hexdigest() != row.extraction_hash:
        raise SigningRejectedError("INVOICE_EXTRACTION_CHANGED")
    fields = InvoiceFields.model_validate_json(row.extraction_json)
    checked = json.loads(row.checks_json or "{}")
    if (
        checked.get("learned_screening_enabled") != s.learned_screening_enabled
        or checked.get("invoice_learned_screening_enabled") != s.invoice_learned_screening_enabled
        or checked.get("learned_screening_evaluated") != s.invoice_learned_evaluated
    ):
        raise SigningRejectedError("INVOICE_SCREENING_CONTEXT_CHANGED")
    if learned_invoice_screening_enabled() and not valid_clearance(
        checked.get("screening"), row.document_text
    ):
        raise SigningRejectedError("INVOICE_SCREENING_CLEARANCE_INVALID")
    vendor, _, _, failures = await assess(session, row, fields)
    if (
        failures
        or vendor is None
        or vendor.version != row.vendor_version
        or vendor.id != row.vendor_id
        or vendor.payout_address.lower() != action.recipient.lower()
        or action.chain_id != 11155111
        or int(eth_to_wei(fields.amount_eth)) != action.amount_wei
        or action.action_digest_without_nonce() != row.action_digest
    ):
        raise SigningRejectedError("INVOICE_AUTHORITY_CHANGED")


async def execute_invoice(factory, invoice_id):
    s = get_settings()
    if (
        not s.invoice_intake_enabled
        or not s.invoice_auto_execute_enabled
        or not s.auto_execute_enabled
    ):
        return
    if s.execution_mode == "sepolia" and not s.invoice_live_execution_enabled:
        return
    from app.api.routes.proposals import (
        audit_service,
        blockchain_service,
        capability_service,
        isolated_signer,
    )
    from app.services.execution import execute_payment

    async with factory() as session:
        await lock_execution(session)
        row = await session.get(InvoiceRecord, invoice_id, populate_existing=True)
        if row is None or row.state != "CHECKED" or not row.proposal_id:
            return
        pending = await session.scalar(
            select(ExecutionAttempt.id)
            .where(
                ExecutionAttempt.status.in_(("PREPARED", "SIGNED", "UNCERTAIN", "SUBMITTED")),
                ExecutionAttempt.proposal_id != row.proposal_id,
                ~(
                    (ExecutionAttempt.execution_mode == "simulated")
                    & (ExecutionAttempt.status == "SUBMITTED")
                ),
            )
            .limit(1)
        )
        if pending:
            return
        await emit(session, row, "EXECUTING", "SHARED_COORDINATOR")
        try:
            result = await execute_payment(
                session,
                row.proposal_id,
                capability_service,
                isolated_signer,
                blockchain_service,
                audit_service,
            )
            await emit(
                session,
                row,
                "SIMULATED" if s.execution_mode == "simulated" else "PAID",
                "NOT_BROADCAST" if s.execution_mode == "simulated" else result.status,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            row = await session.get(InvoiceRecord, invoice_id, populate_existing=True)
            attempt = await session.scalar(
                select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == row.proposal_id)
            )
            await emit(
                session,
                row,
                "UNCERTAIN" if attempt and attempt.raw_transaction else "NEEDS_HUMAN_REVIEW",
                "EXECUTION_NOT_CONFIRMED",
            )
            await session.commit()


async def reconcile_invoices(factory):
    from app.api.routes.proposals import blockchain_service
    from app.models import Transaction
    from app.services.receipt import reconcile_receipt

    async with factory() as session:
        ids = list(
            (
                await session.scalars(
                    select(InvoiceRecord.id).where(
                        InvoiceRecord.state.in_(("PAID", "UNCERTAIN", "CHECKED", "EXECUTING"))
                    )
                )
            ).all()
        )
    for invoice_id in ids:
        async with factory() as session:
            row = await session.get(InvoiceRecord, invoice_id)
            if row.state == "CHECKED":
                await session.commit()
                await execute_invoice(factory, invoice_id)
                continue
            tx = await session.scalar(
                select(Transaction).where(Transaction.proposal_id == row.proposal_id)
            )
            if tx:
                await reconcile_receipt(session, tx, blockchain_service)
                if tx.execution_outcome in ("CONFIRMED", "REVERTED"):
                    await emit(
                        session,
                        row,
                        "VERIFIED" if tx.execution_outcome == "CONFIRMED" else "REVERTED",
                        tx.execution_outcome,
                    )
            await session.commit()
