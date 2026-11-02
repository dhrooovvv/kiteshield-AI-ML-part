"""Exact saved-vendor resolution. Names never grant authority or replace policy checks."""

import json
import re

from sqlalchemy import select

from app.exceptions import SigningRejectedError
from app.models import ExecutionAttempt, Policy
from app.models.assistant import AssistantPaymentDraft, AssistantVendorBinding
from app.models.invoices import Vendor
from app.services.agent import AgentService
from app.services.funding import refuse


async def resolve_vendor(session, prompt):
    vendors = (await session.scalars(select(Vendor).where(Vendor.active.is_(True)))).all()
    policy = await session.scalar(
        select(Policy).where(Policy.is_active.is_(True)).order_by(Policy.version.desc()).limit(1)
    )
    recipients = json.loads(policy.allowed_recipients or "[]") if policy else []
    suffix = re.fullmatch(
        r"\s*(?:please\s+)?(?:send|pay|transfer)\s+"
        r"([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(ETH|ether|wei)\s+to\s+"
        r"(?:the\s+)?(?:saved\s+)?(?:account|wallet|address)\s+ending"
        r"(?:\s+(?:with|in))?\s+(.+?)\s*[.!]?\s*",
        prompt, re.I,
    )
    if suffix:
        spoken = suffix[3].strip().lower()
        words = dict(zip(
            ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"),
            "0123456789", strict=True,
        ))
        parts = spoken.split()
        if parts and all(part in words for part in parts):
            ending = "".join(words[part] for part in parts)
        elif re.fullmatch(r"[0-9a-f](?:\s*[0-9a-f])*", spoken):
            ending = re.sub(r"\s+", "", spoken)
        else:
            refuse("INVALID_ADDRESS_SUFFIX", "Use 3 to 12 exact address-ending characters.")
        if not 3 <= len(ending) <= 12:
            refuse("INVALID_ADDRESS_SUFFIX", "Use 3 to 12 exact address-ending characters.")
        matches = {address.lower(): address for address in recipients
                   if re.fullmatch(r"0x[0-9a-fA-F]{40}", address)
                   and address.lower().endswith(ending)}
        if not matches:
            refuse("RECIPIENT_NOT_FOUND", "No policy-approved recipient has that address ending. "
                   "Use a full approved Ethereum address or register the recipient first.")
        if len(matches) != 1:
            refuse("RECIPIENT_AMBIGUOUS", "Several approved recipients match that ending. "
                   "Use the exact vendor name or full address; no payment was created.")
        address = next(iter(matches.values()))
        matched_vendors = [v for v in vendors if v.payout_address.lower() == address.lower()]
        if len(matched_vendors) > 1:
            refuse("RECIPIENT_AMBIGUOUS", "Several vendor records use that recipient. "
                   "Use one exact vendor name.")
        vendor = matched_vendors[0] if matched_vendors else None
        canonical = f"Send {suffix[1]} {suffix[2]} to {address}"
    else:
        canonical, vendor = await resolve_vendor_name(session, prompt, vendors)
    if vendor and vendor.payout_address.lower() not in {value.lower() for value in recipients}:
        refuse("RECIPIENT_NOT_ALLOWLISTED", "The saved vendor is not in the current policy allowlist.")
    amount = int(AgentService.extract_explicit_amount(canonical))
    if vendor and amount > int(vendor.maximum_wei):
        refuse("VENDOR_LIMIT_EXCEEDED", "This amount exceeds the saved vendor limit.")
    return canonical, vendor


async def resolve_vendor_name(session, prompt, vendors):
    match = re.fullmatch(
        r"\s*(?:please\s+)?pay\s+(.+?)\s+([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(ETH|ether|wei)\s*[.!]?\s*",
        prompt,
        re.I,
    )
    if not match:
        refuse(
            "RECIPIENT_REQUIRED",
            "Use one full address, or say: Pay Exact Vendor Name 0.00001 ETH. "
            "Rupee and bank payouts are not supported.",
        )
    matched = [row for row in vendors if row.name.casefold() == match[1].strip().casefold()]
    if len(matched) != 1:
        refuse(
            "EXACT_VENDOR_REQUIRED",
            "Choose one exact approved vendor. Unknown or ambiguous names require "
            "registry review in Accounts Payable.",
        )
    vendor = matched[0]
    canonical = f"Send {match[2]} {match[3]} to {vendor.payout_address}"
    return canonical, vendor


async def validate_binding(session, draft):
    binding = await session.get(AssistantVendorBinding, draft.id, populate_existing=True)
    if not binding:
        return
    vendor = await session.get(Vendor, binding.vendor_id, populate_existing=True)
    if (
        not vendor
        or not vendor.active
        or vendor.version != binding.vendor_version
        or vendor.payout_address.lower() != draft.recipient.lower()
        or int(draft.amount_wei) > int(vendor.maximum_wei)
    ):
        raise SigningRejectedError("Saved vendor changed; request a fresh payment draft")


async def validate_vendor_authority(session, action):
    draft = await session.scalar(
        select(AssistantPaymentDraft)
        .where(AssistantPaymentDraft.proposal_id == action.proposal_id)
        .execution_options(populate_existing=True)
    )
    if not draft:
        return
    if (draft.recipient.lower() != action.recipient.lower()
            or int(draft.amount_wei) != action.amount_wei
            or action.chain_id != 11155111):
        raise SigningRejectedError("Saved-recipient draft does not match the executable action")
    attempt = await session.scalar(
        select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == action.proposal_id)
    )
    if attempt and attempt.raw_transaction:
        return  # Existing bytes may still need receipt/recovery; never create a new signature.
    await validate_binding(session, draft)
