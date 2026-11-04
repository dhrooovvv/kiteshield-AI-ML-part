"""Typed vault records. No private keys, no chain event can create an admin grant."""

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint

from app.models import Base, generate_uuid, utc_now_str


class VaultRegistry(Base):
    __tablename__ = "vault_registry"
    id = Column(String, primary_key=True, default="global")
    owner = Column(String, nullable=False)
    agent = Column(String, nullable=False)
    address = Column(String, nullable=True)
    runtime_hash = Column(String, nullable=False)
    epoch = Column(Integer, nullable=False, default=0)
    revision = Column(Integer, nullable=False, default=0)
    configured = Column(Boolean, nullable=False, default=False)


class VaultOperation(Base):
    __tablename__ = "vault_operations"
    id = Column(String, primary_key=True, default=generate_uuid)
    request_key = Column(String, nullable=False, unique=True)
    proposal_id = Column(String, ForeignKey("proposals.id"), nullable=True, unique=True)
    kind = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    authority_digest = Column(String, nullable=False)
    authorized_by = Column(String, nullable=False)
    policy_version = Column(Integer, nullable=False)
    approval_id = Column(String, nullable=True)
    sender = Column(String, nullable=False)
    nonce = Column(Integer, nullable=True)
    execution_mode = Column(String, nullable=False)
    status = Column(String, nullable=False, default="DRAFT")
    envelope = Column(Text, nullable=True)
    raw_transaction = Column(Text, nullable=True)
    tx_hash = Column(String, nullable=True)
    receipt = Column(Text, nullable=True)
    applied = Column(Boolean, nullable=False, default=False)
    created_at = Column(String, nullable=False, default=utc_now_str)
    __table_args__ = (
        UniqueConstraint("sender", "execution_mode", "nonce", name="uq_vault_sender_nonce"),
    )


class VaultCapability(Base):
    __tablename__ = "vault_capabilities"
    jti = Column(String, primary_key=True)
    operation_id = Column(String, ForeignKey("vault_operations.id"), nullable=False)
    digest = Column(String, nullable=False)
    consumed = Column(Boolean, nullable=False, default=False)
    expires_at = Column(String, nullable=False)
