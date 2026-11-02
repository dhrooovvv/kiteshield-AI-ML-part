"""Additive invoice records. No secrets or signed bytes are stored here."""

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text

from app.models import Base, generate_uuid, utc_now_str


class Vendor(Base):
    __tablename__ = "invoice_vendors"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    payout_address = Column(String, nullable=False)
    maximum_wei = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    active = Column(Boolean, nullable=False, default=True)
    updated_by = Column(String, nullable=False)


class InvoiceRecord(Base):
    __tablename__ = "invoice_records"
    id = Column(String, primary_key=True, default=generate_uuid)
    document_hash = Column(String, nullable=False, unique=True)
    document_text = Column(Text, nullable=False)
    state = Column(String, nullable=False, default="OBSERVED")
    reason = Column(String, nullable=True)
    extraction_json = Column(Text, nullable=True)
    extraction_hash = Column(String, nullable=True)
    vendor_id = Column(String, ForeignKey("invoice_vendors.id"), nullable=True)
    vendor_version = Column(Integer, nullable=True)
    duplicate_key = Column(String, nullable=True, unique=True)
    invoice_identity = Column(String, nullable=True, unique=True)
    proposal_id = Column(String, ForeignKey("proposals.id"), nullable=True, unique=True)
    action_digest = Column(String, nullable=True)
    checks_json = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    claim_until = Column(String, nullable=True)
    created_at = Column(String, nullable=False, default=utc_now_str)


class InvoiceEvent(Base):
    __tablename__ = "invoice_events"
    id = Column(String, primary_key=True, default=generate_uuid)
    invoice_id = Column(String, ForeignKey("invoice_records.id"), nullable=False)
    stage = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    created_at = Column(String, nullable=False, default=utc_now_str)


class InvoiceIdleState(Base):
    __tablename__ = "invoice_idle_state"
    id = Column(String, primary_key=True, default="global")
    count = Column(Integer, nullable=False, default=0)
    last_reason = Column(String, nullable=False, default="NO_NEW_FILES")
    observed_at = Column(String, nullable=False, default=utc_now_str)
