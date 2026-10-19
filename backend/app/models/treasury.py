"""Additive treasury tables. Action history survives mandate edits and disabling."""

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text

from app.models import Base, generate_uuid, utc_now_str


class TreasuryMandate(Base):
    __tablename__ = "treasury_mandates"
    id = Column(String, primary_key=True, default="global")
    version = Column(Integer, nullable=False, default=1)
    config_json = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    mode = Column(String, nullable=False, default="plan_only")
    created_by = Column(String, nullable=False)
    updated_by = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=utc_now_str)
    updated_at = Column(String, nullable=False, default=utc_now_str)
    observation_json = Column(Text, nullable=True)
    last_state = Column(String, nullable=True)
    last_plan_json = Column(Text, nullable=True)
    claim_token = Column(String, nullable=True)
    claim_until = Column(String, nullable=True)


class TreasuryAction(Base):
    __tablename__ = "treasury_actions"
    id = Column(String, primary_key=True, default=generate_uuid)
    mandate_id = Column(String, ForeignKey("treasury_mandates.id"), nullable=False)
    mandate_version = Column(Integer, nullable=False)
    config_json = Column(Text, nullable=False)
    observation_json = Column(Text, nullable=False)
    plan_json = Column(Text, nullable=False)
    state = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    claim_token = Column(String, nullable=False, unique=True)
    proposal_id = Column(String, ForeignKey("proposals.id"), nullable=True, unique=True)
    action_digest = Column(String, nullable=True)
    initiated_at = Column(String, nullable=True, index=True)
    created_at = Column(String, nullable=False, default=utc_now_str)
    updated_at = Column(String, nullable=False, default=utc_now_str)
