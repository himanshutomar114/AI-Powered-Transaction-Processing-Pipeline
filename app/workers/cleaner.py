import re
import uuid
from datetime import datetime

import pandas as pd


DOMESTIC_MERCHANTS = {"swiggy", "ola", "irctc", "zomato", "flipkart", "myntra"}


def clean_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Full cleaning pipeline. Returns cleaned DataFrame."""
    df = df.copy()

    # ── 1. Normalise column names ──────────────────────────────────────────
    df.columns = [c.strip().lower() for c in df.columns]

    # ── 2. Remove exact duplicate rows ────────────────────────────────────
    df.drop_duplicates(inplace=True)

    # ── 3. Fill missing txn_id ─────────────────────────────────────────────
    df["txn_id"] = df["txn_id"].apply(
        lambda x: x if pd.notna(x) and str(x).strip() else str(uuid.uuid4())
    )

    # ── 4. Normalise dates to ISO 8601 ─────────────────────────────────────
    df["date"] = df["date"].apply(_parse_date)

    # ── 5. Strip currency symbols from amount ─────────────────────────────
    df["amount"] = df["amount"].apply(_clean_amount)

    # ── 6. Uppercase currency & status ────────────────────────────────────
    df["currency"] = df["currency"].str.strip().str.upper()
    df["status"] = df["status"].str.strip().str.upper()

    # ── 7. Fill missing category ───────────────────────────────────────────
    df["category"] = df["category"].apply(
        lambda x: x if pd.notna(x) and str(x).strip() else "Uncategorised"
    )

    # ── 8. Strip whitespace from text fields ──────────────────────────────
    for col in ["merchant", "account_id", "notes"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: str(x).strip() if pd.notna(x) else "")

    return df.reset_index(drop=True)


def _parse_date(raw) -> str:
    if pd.isna(raw) or str(raw).strip() == "":
        return ""
    raw = str(raw).strip()
    for fmt in ("%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return raw  # return as-is if unparseable


def _clean_amount(raw) -> float:
    if pd.isna(raw):
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", str(raw))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Add is_anomaly and anomaly_reason columns."""
    df = df.copy()
    df["is_anomaly"] = False
    df["anomaly_reason"] = ""

    # Statistical outlier: amount > 3x account median
    for acct, group in df.groupby("account_id"):
        if group.empty:
            continue
        median = group["amount"].median()
        threshold = median * 3
        mask = (df["account_id"] == acct) & (df["amount"] > threshold)
        df.loc[mask, "is_anomaly"] = True
        df.loc[mask, "anomaly_reason"] = df.loc[mask, "anomaly_reason"].apply(
            lambda r: _append(r, f"Amount exceeds 3x account median ({median:.2f})")
        )

    # Currency mismatch: USD + domestic merchant
    domestic_mask = (
        (df["currency"] == "USD") &
        (df["merchant"].str.lower().isin(DOMESTIC_MERCHANTS))
    )
    df.loc[domestic_mask, "is_anomaly"] = True
    df.loc[domestic_mask, "anomaly_reason"] = df.loc[domestic_mask, "anomaly_reason"].apply(
        lambda r: _append(r, "USD currency with domestic-only merchant")
    )

    return df


def _append(existing: str, new: str) -> str:
    return f"{existing}; {new}" if existing else new
