import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    status = Column(String(20), default="pending")  # pending/processing/completed/failed
    row_count_raw = Column(Integer, default=0)
    row_count_clean = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    transactions = relationship("Transaction", back_populates="job", cascade="all, delete")
    summary = relationship("JobSummary", back_populates="job", uselist=False, cascade="all, delete")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    txn_id = Column(String(100), nullable=True)
    date = Column(String(20), nullable=True)          # ISO 8601 string
    merchant = Column(String(255), nullable=True)
    amount = Column(Float, nullable=True)
    currency = Column(String(10), nullable=True)
    status = Column(String(20), nullable=True)
    category = Column(String(100), nullable=True)
    account_id = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    is_anomaly = Column(Boolean, default=False)
    anomaly_reason = Column(Text, nullable=True)
    llm_category = Column(String(100), nullable=True)
    llm_raw_response = Column(Text, nullable=True)
    llm_failed = Column(Boolean, default=False)

    job = relationship("Job", back_populates="transactions")


class JobSummary(Base):
    __tablename__ = "job_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, unique=True)
    total_spend_inr = Column(Float, default=0.0)
    total_spend_usd = Column(Float, default=0.0)
    top_merchants = Column(JSON, default=list)
    anomaly_count = Column(Integer, default=0)
    category_breakdown = Column(JSON, default=dict)
    narrative = Column(Text, nullable=True)
    risk_level = Column(String(10), nullable=True)   # low/medium/high

    job = relationship("Job", back_populates="summary")
