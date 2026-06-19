import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.schemas import (
    JobCreateResponse, JobListItem, JobResultsResponse, JobStatusResponse
)
from app.core.config import settings
from app.db.models import Job, JobSummary, Transaction
from app.db.session import get_db
from app.workers.tasks import process_csv

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/upload", response_model=JobCreateResponse, status_code=202)
async def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    # Save upload to disk
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    safe_name = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(settings.UPLOAD_DIR, safe_name)
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    with open(file_path, "wb") as f:
        f.write(contents)

    # Create job record
    job = Job(filename=file.filename, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    # Enqueue
    process_csv.delay(str(job.id), file_path)

    return JobCreateResponse(
        job_id=job.id,
        status=job.status,
        message="Job enqueued. Poll /jobs/{job_id}/status for updates.",
    )


@router.get("/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    summary_data = None
    if job.status == "completed" and job.summary:
        s = job.summary
        summary_data = {
            "total_spend_inr": s.total_spend_inr,
            "total_spend_usd": s.total_spend_usd,
            "top_merchants": s.top_merchants,
            "anomaly_count": s.anomaly_count,
            "risk_level": s.risk_level,
            "narrative": s.narrative,
        }

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        summary=summary_data,
    )


@router.get("/{job_id}/results", response_model=JobResultsResponse)
def get_job_results(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "completed":
        raise HTTPException(
            status_code=202,
            detail=f"Job is not yet completed. Current status: {job.status}",
        )

    transactions = db.query(Transaction).filter(Transaction.job_id == job_id).all()
    anomalies = [t for t in transactions if t.is_anomaly]

    # Category spend breakdown
    category_breakdown: dict[str, float] = {}
    for t in transactions:
        cat = t.llm_category or t.category or "Other"
        category_breakdown[cat] = category_breakdown.get(cat, 0) + (t.amount or 0)

    summary_data = None
    if job.summary:
        s = job.summary
        summary_data = {
            "total_spend_inr": s.total_spend_inr,
            "total_spend_usd": s.total_spend_usd,
            "top_merchants": s.top_merchants,
            "anomaly_count": s.anomaly_count,
            "narrative": s.narrative,
            "risk_level": s.risk_level,
        }

    return JobResultsResponse(
        job_id=job.id,
        status=job.status,
        transactions=transactions,
        anomalies=anomalies,
        category_breakdown=category_breakdown,
        summary=summary_data,
    )


@router.get("", response_model=list[JobListItem])
def list_jobs(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)
    jobs = query.order_by(Job.created_at.desc()).all()
    return [
        JobListItem(
            job_id=j.id,
            filename=j.filename,
            status=j.status,
            row_count_raw=j.row_count_raw,
            created_at=j.created_at,
        )
        for j in jobs
    ]
