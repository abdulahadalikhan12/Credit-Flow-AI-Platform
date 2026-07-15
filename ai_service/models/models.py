import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from shared.database import Base

class PromptHistory(Base):
    __tablename__ = "prompt_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    prompt = Column(String, nullable=False)
    response = Column(String, nullable=False)
    tokens_used = Column(Integer, default=0, nullable=False)
    cost = Column(Integer, default=0, nullable=False) # credit cost
    model = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, default="running", nullable=False) # running, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id = Column(String, primary_key=True, index=True)
    processed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
