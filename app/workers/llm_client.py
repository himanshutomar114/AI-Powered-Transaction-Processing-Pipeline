import json
import logging
import time
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)

VALID_CATEGORIES = [
    "Food", "Shopping", "Travel", "Transport",
    "Utilities", "Cash Withdrawal", "Entertainment", "Other"
]

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _call_gemini(prompt: str) -> str:
    """Raw Gemini API call with retry."""
    response = httpx.post(
        GEMINI_URL,
        params={"key": settings.GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def classify_transactions_batch(transactions: list[dict]) -> dict[str, str]:
    """
    Given a list of dicts with keys: txn_id, merchant, amount, currency, notes
    Returns a mapping of txn_id -> category string.
    """
    if not transactions:
        return {}

    rows = "\n".join(
        f'{t["txn_id"]} | {t["merchant"]} | {t["amount"]} {t["currency"]} | {t.get("notes","")}'
        for t in transactions
    )

    prompt = f"""You are a financial transaction classifier.
Classify each transaction below into exactly one of these categories:
{', '.join(VALID_CATEGORIES)}

Return ONLY a valid JSON object mapping txn_id to category. No explanation.
Example: {{"TXN001": "Food", "TXN002": "Travel"}}

Transactions (format: txn_id | merchant | amount currency | notes):
{rows}
"""
    raw = _call_gemini(prompt)
    # Strip markdown fences if present
    raw = raw.strip().strip("```json").strip("```").strip()
    try:
        result = json.loads(raw)
        # Validate categories
        return {k: v if v in VALID_CATEGORIES else "Other" for k, v in result.items()}
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM classification response: %s", raw)
        return {}


def generate_narrative_summary(transactions: list[dict]) -> Optional[dict]:
    """
    Generate a structured narrative summary from cleaned transactions.
    Returns dict with: total_spend_inr, total_spend_usd, top_merchants,
                       anomaly_count, narrative, risk_level
    """
    if not transactions:
        return None

    # Compute basic stats to feed the LLM
    inr_total = sum(t["amount"] for t in transactions if t.get("currency") == "INR")
    usd_total = sum(t["amount"] for t in transactions if t.get("currency") == "USD")
    anomaly_count = sum(1 for t in transactions if t.get("is_anomaly"))

    from collections import Counter
    merchant_counts = Counter(t["merchant"] for t in transactions if t.get("merchant"))
    top_merchants = [m for m, _ in merchant_counts.most_common(3)]

    category_spend: dict[str, float] = {}
    for t in transactions:
        cat = t.get("llm_category") or t.get("category") or "Other"
        category_spend[cat] = category_spend.get(cat, 0) + t.get("amount", 0)

    prompt = f"""You are a financial analyst. Given these transaction statistics, 
produce a JSON summary. Respond with ONLY valid JSON, no markdown.

Stats:
- Total INR spend: {inr_total:.2f}
- Total USD spend: {usd_total:.2f}
- Top merchants: {top_merchants}
- Anomaly count: {anomaly_count}
- Total transactions: {len(transactions)}
- Spend by category: {json.dumps(category_spend)}

Return this exact JSON structure:
{{
  "narrative": "2-3 sentence spending summary",
  "risk_level": "low|medium|high",
  "insights": "one sentence about the most notable pattern"
}}

Risk level guide: high if anomaly_count > 5 or any single transaction > 50000 INR,
medium if anomaly_count 2-5, low otherwise.
"""
    raw = _call_gemini(prompt)
    raw = raw.strip().strip("```json").strip("```").strip()
    try:
        llm_data = json.loads(raw)
    except json.JSONDecodeError:
        llm_data = {"narrative": raw[:500], "risk_level": "medium", "insights": ""}

    return {
        "total_spend_inr": round(inr_total, 2),
        "total_spend_usd": round(usd_total, 2),
        "top_merchants": top_merchants,
        "anomaly_count": anomaly_count,
        "narrative": llm_data.get("narrative", ""),
        "risk_level": llm_data.get("risk_level", "medium"),
        "category_breakdown": category_spend,
    }
