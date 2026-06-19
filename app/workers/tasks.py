import logging
import os
from datetime import datetime

import pandas as pd
from celery import shared_task
from tenacity import RetryError

from app.db.session import SessionLocal
from app.db.models import Job, JobSummary, Transaction
from app.workers.celery_app import celery_app
from app.workers.cleaner import clean_transactions, detect_anomalies
from app.workers.llm_client import classify_transactions_batch, generate_narrative_summary

logger = logging.getLogger(__name__)

BATCH_SIZE = 20  # LLM classification batch size


@celery_app.task(bind=True, name="process_csv")
def process_csv(self, job_id: str, file_path: str):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("Job %s not found", job_id)
            return

        job.status = "processing"
        db.commit()

        # ── Step 1: Load CSV ───────────────────────────────────────────────
        df = pd.read_csv(file_path)
        job.row_count_raw = len(df)
        db.commit()

        # ── Step 2: Clean ──────────────────────────────────────────────────
        df = clean_transactions(df)

        # ── Step 3: Anomaly detection ──────────────────────────────────────
        df = detect_anomalies(df)
        job.row_count_clean = len(df)
        db.commit()

        # ── Step 4: LLM classification (batched, with retry) ───────────────
        uncategorised = df[df["category"] == "Uncategorised"].copy()
        llm_categories: dict[str, str] = {}

        if not uncategorised.empty:
            batches = [
                uncategorised.iloc[i: i + BATCH_SIZE]
                for i in range(0, len(uncategorised), BATCH_SIZE)
            ]
            for batch in batches:
                txns_for_llm = batch[["txn_id", "merchant", "amount", "currency", "notes"]].to_dict("records")
                try:
                    result = classify_transactions_batch(txns_for_llm)
                    llm_categories.update(result)
                except (RetryError, Exception) as exc:
                    logger.warning("LLM classification batch failed: %s", exc)
                    # Mark those rows as llm_failed
                    for t in txns_for_llm:
                        llm_categories[t["txn_id"]] = "__failed__"

        # Apply LLM categories back to df
        df["llm_category"] = df["txn_id"].map(llm_categories).fillna("")
        df["llm_failed"] = df["llm_category"] == "__failed__"
        df["llm_category"] = df["llm_category"].replace("__failed__", "")

        # ── Step 5: Persist transactions ───────────────────────────────────
        db.query(Transaction).filter(Transaction.job_id == job_id).delete()
        txn_records = []
        for _, row in df.iterrows():
            effective_category = row.get("llm_category") or row.get("category") or "Uncategorised"
            txn_records.append(Transaction(
                job_id=job_id,
                txn_id=row.get("txn_id"),
                date=row.get("date"),
                merchant=row.get("merchant"),
                amount=float(row.get("amount", 0)),
                currency=row.get("currency"),
                status=row.get("status"),
                category=effective_category,
                account_id=row.get("account_id"),
                notes=row.get("notes"),
                is_anomaly=bool(row.get("is_anomaly", False)),
                anomaly_reason=row.get("anomaly_reason") or "",
                llm_category=row.get("llm_category") or "",
                llm_failed=bool(row.get("llm_failed", False)),
            ))
        db.bulk_save_objects(txn_records)
        db.commit()

        # ── Step 6: LLM narrative summary ──────────────────────────────────
        all_txns = [
            {
                "merchant": t.merchant,
                "amount": t.amount,
                "currency": t.currency,
                "category": t.category,
                "llm_category": t.llm_category,
                "is_anomaly": t.is_anomaly,
            }
            for t in txn_records
        ]

        summary_data = None
        try:
            summary_data = generate_narrative_summary(all_txns)
        except (RetryError, Exception) as exc:
            logger.warning("LLM narrative summary failed: %s", exc)

        if summary_data:
            summary = JobSummary(
                job_id=job_id,
                total_spend_inr=summary_data["total_spend_inr"],
                total_spend_usd=summary_data["total_spend_usd"],
                top_merchants=summary_data["top_merchants"],
                anomaly_count=summary_data["anomaly_count"],
                category_breakdown=summary_data["category_breakdown"],
                narrative=summary_data["narrative"],
                risk_level=summary_data["risk_level"],
            )
            db.add(summary)

        # ── Step 7: Mark job complete ──────────────────────────────────────
        job.status = "completed"
        job.completed_at = datetime.utcnow()
        db.commit()

        # Optionally clean up uploaded file
        try:
            os.remove(file_path)
        except OSError:
            pass

    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(exc)
            db.commit()
    finally:
        db.close()
