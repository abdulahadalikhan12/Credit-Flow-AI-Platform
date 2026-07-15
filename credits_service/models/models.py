import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from shared.database import Base

class CreditLedgerEntry(Base):
    __tablename__ = "credits_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    amount = Column(Integer, nullable=False) # positive for credit, negative for debit
    transaction_type = Column(String, nullable=False) # grant, debit, transfer_in, transfer_out, refund
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class MarketplaceListing(Base):
    __tablename__ = "marketplace_listings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    amount = Column(Integer, nullable=False) # credits to sell
    price = Column(Integer, nullable=False) # price in cents (USD)
    status = Column(String, default="active", nullable=False) # active, sold, canceled
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id = Column(String, primary_key=True, index=True)
    processed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
