"""Incoming faucet requests only; never wallet transactions or signing payloads."""

from sqlalchemy import Column, Integer, String

from app.models import Base, utc_now_str


class FundingRequest(Base):
    __tablename__ = "funding_requests"
    id = Column(String, primary_key=True)
    address = Column(String(42), nullable=False)
    actor = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    state = Column(String, nullable=False, default="PREPARED")
    created_at = Column(String, nullable=False, default=utc_now_str)
    requested_at = Column(String, nullable=True)
    tx_hash = Column(String, nullable=True, unique=True)
    amount_wei = Column(String, nullable=True)
    block_number = Column(Integer, nullable=True)
    reason = Column(String, nullable=True)
