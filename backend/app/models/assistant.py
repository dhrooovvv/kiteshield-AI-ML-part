"""Immutable assistant payment drafts; no signing payloads or model authority."""

from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.models import Base, generate_uuid, utc_now_str


class AssistantPaymentDraft(Base):
    __tablename__ = "assistant_payment_drafts"
    id = Column(String, primary_key=True, default=generate_uuid)
    prompt = Column(Text, nullable=False)
    prompt_digest = Column(String(64), nullable=False, index=True)
    actor = Column(String, nullable=False)
    recipient = Column(String(42), nullable=False)
    amount_wei = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=utc_now_str)
    proposal_id = Column(String, ForeignKey("proposals.id"), nullable=True, unique=True)


class AssistantVendorBinding(Base):
    __tablename__ = "assistant_vendor_bindings"
    draft_id = Column(String, ForeignKey("assistant_payment_drafts.id"), primary_key=True)
    vendor_id = Column(String, ForeignKey("invoice_vendors.id"), nullable=False)
    vendor_version = Column(Integer, nullable=False)
    original_request = Column(Text, nullable=False)
