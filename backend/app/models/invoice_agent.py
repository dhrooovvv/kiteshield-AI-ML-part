"""Persistent invoice command queue. No credentials or executable model tools."""

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text

from app.models import Base, generate_uuid, utc_now_str


class InvoiceAgentTask(Base):
    __tablename__ = "invoice_agent_tasks"
    id = Column(String, primary_key=True, default=generate_uuid)
    actor = Column(String, nullable=False)
    command_digest = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False)
    state = Column(String, nullable=False, default="QUEUED")
    stage = Column(String, nullable=False, default="QUEUED")
    cancel_requested = Column(Boolean, nullable=False, default=False)
    reason = Column(String, nullable=True)
    lease_until = Column(String, nullable=True)
    created_at = Column(String, nullable=False, default=utc_now_str)
    updated_at = Column(String, nullable=False, default=utc_now_str)


class InvoiceAgentItem(Base):
    __tablename__ = "invoice_agent_items"
    id = Column(String, primary_key=True, default=generate_uuid)
    task_id = Column(String, ForeignKey("invoice_agent_tasks.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    filename = Column(String, nullable=False)
    document_text = Column(Text, nullable=True)
    document_hash = Column(String, nullable=False)
    invoice_id = Column(String, ForeignKey("invoice_records.id"), nullable=True)
