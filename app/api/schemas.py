from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class JobCreateResponse(BaseModel):
    job_id: UUID
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    filename: str
    row_count_raw: int
    row_count_clean: int
    created_at: datetime
    completed_at: Optional[datetime]
    error_message: Optional[str]
    summary: Optional[dict[str, Any]] = None


class TransactionOut(BaseModel):
    id: UUID
    txn_id: Optional[str]
    date: Optional[str]
    merchant: Optional[str]
    amount: Optional[float]
    currency: Optional[str]
    status: Optional[str]
    category: Optional[str]
    account_id: Optional[str]
    notes: Optional[str]
    is_anomaly: bool
    anomaly_reason: Optional[str]
    llm_category: Optional[str]
    llm_failed: bool

    class Config:
        from_attributes = True


class JobResultsResponse(BaseModel):
    job_id: UUID
    status: str
    transactions: list[TransactionOut]
    anomalies: list[TransactionOut]
    category_breakdown: dict[str, float]
    summary: Optional[dict[str, Any]]


class JobListItem(BaseModel):
    job_id: UUID
    filename: str
    status: str
    row_count_raw: int
    created_at: datetime

    class Config:
        from_attributes = True
