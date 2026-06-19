# AI-Powered Transaction Processing Pipeline

A backend API that accepts a dirty financial transactions CSV, processes it asynchronously via a job queue, uses Gemini 1.5 Flash to classify transactions and flag anomalies, and returns a structured summary report.

## Stack

| Component | Technology |
|-----------|-----------|
| API | FastAPI |
| Database | PostgreSQL 15 |
| Job Queue | Celery + Redis |
| LLM | Gemini 1.5 Flash (free tier) |
| Container | Docker + Docker Compose |

## Quick Start

### 1. Clone and configure

```bash
git clone <your-repo-url>
cd txn_pipeline
cp .env.example .env
# Edit .env and add your Gemini API key
# Get a free key at: https://aistudio.google.com/app/apikey
```

### 2. Start everything

```bash
docker compose up --build
```

That's it. All services (API, Celery worker, Redis, PostgreSQL) start automatically. Alembic migrations run on boot.

The API is available at **http://localhost:8000**

Interactive docs: **http://localhost:8000/docs**

---

## API Endpoints

### POST /jobs/upload
Upload a CSV file to start a processing job.

```bash
curl -X POST http://localhost:8000/jobs/upload \
  -F "file=@transactions.csv"
```

Response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Job enqueued. Poll /jobs/{job_id}/status for updates."
}
```

---

### GET /jobs/{job_id}/status
Poll for job status. Returns `pending`, `processing`, `completed`, or `failed`.

```bash
curl http://localhost:8000/jobs/550e8400-e29b-41d4-a716-446655440000/status
```

Response (completed):
```json
{
  "job_id": "550e8400-...",
  "status": "completed",
  "filename": "transactions.csv",
  "row_count_raw": 91,
  "row_count_clean": 90,
  "created_at": "2024-01-15T10:00:00",
  "completed_at": "2024-01-15T10:00:12",
  "summary": {
    "total_spend_inr": 245600.50,
    "total_spend_usd": 5250.00,
    "top_merchants": ["Amazon", "Swiggy", "MakeMyTrip"],
    "anomaly_count": 6,
    "risk_level": "high",
    "narrative": "Spending was concentrated in travel and food categories..."
  }
}
```

---

### GET /jobs/{job_id}/results
Get the full structured output after job completes.

```bash
curl http://localhost:8000/jobs/550e8400-e29b-41d4-a716-446655440000/results
```

Response:
```json
{
  "job_id": "550e8400-...",
  "status": "completed",
  "transactions": [...],
  "anomalies": [
    {
      "txn_id": "TXN005",
      "merchant": "IRCTC",
      "amount": 8500.0,
      "currency": "USD",
      "is_anomaly": true,
      "anomaly_reason": "USD currency with domestic-only merchant"
    }
  ],
  "category_breakdown": {
    "Food": 8540.00,
    "Travel": 183200.00,
    "Transport": 3920.00
  },
  "summary": { ... }
}
```

---

### GET /jobs
List all jobs, with optional status filter.

```bash
# All jobs
curl http://localhost:8000/jobs

# Filter by status
curl "http://localhost:8000/jobs?status=completed"
curl "http://localhost:8000/jobs?status=failed"
```

---

### GET /health
```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

---

## Processing Pipeline

When a CSV is uploaded, the Celery worker executes these steps:

1. **Data Cleaning**
   - Normalise dates to ISO 8601 (handles `DD-MM-YYYY` and `YYYY/MM/DD`)
   - Strip `$` prefix from amounts
   - Uppercase `currency` and `status` fields
   - Fill blank `category` → `"Uncategorised"`
   - Remove exact duplicate rows
   - Generate UUID for blank `txn_id` values

2. **Anomaly Detection**
   - Flag transactions where `amount > 3× account median`
   - Flag rows with `currency=USD` but a domestic-only merchant (Swiggy, Ola, IRCTC, etc.)

3. **LLM Classification** (batched, 20 rows/call)
   - Transactions with `category=Uncategorised` are sent to Gemini in batches
   - Categories: Food, Shopping, Travel, Transport, Utilities, Cash Withdrawal, Entertainment, Other
   - Retries up to 3× with exponential backoff; marks `llm_failed=true` if all fail

4. **LLM Narrative Summary** (single call)
   - Gemini generates: total spend by currency, top merchants, anomaly count, 2–3 sentence narrative, `risk_level` (low/medium/high)

5. **Persistence** — all results stored in PostgreSQL

---

## Project Structure

```
txn_pipeline/
├── app/
│   ├── api/
│   │   ├── routes.py        # FastAPI endpoint handlers
│   │   └── schemas.py       # Pydantic request/response models
│   ├── core/
│   │   └── config.py        # Settings (env vars)
│   ├── db/
│   │   ├── models.py        # SQLAlchemy ORM models
│   │   └── session.py       # DB engine + session factory
│   ├── workers/
│   │   ├── celery_app.py    # Celery configuration
│   │   ├── cleaner.py       # Data cleaning + anomaly detection
│   │   ├── llm_client.py    # Gemini API client (batching + retry)
│   │   └── tasks.py         # Main Celery task (full pipeline)
│   └── main.py              # FastAPI app entrypoint
├── alembic/                 # DB migrations
├── transactions.csv         # Sample dirty data
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Architecture Diagram

[Link to draw.io diagram — add yours here]

---

## Design Decisions

**Why FastAPI?**  
Async-friendly, fast, and auto-generates OpenAPI docs out of the box. Ideal for an I/O-heavy pipeline.

**Why Celery + Redis over RQ?**  
Celery gives finer control over retry logic, task routing, and concurrency — important for the exponential backoff requirement.

**Why batch LLM calls?**  
Each Gemini API call has latency ~1s. 90 rows × 1 call/row = 90s minimum. Batching 20 rows/call brings this to ~5 calls = ~5s.

**Retry strategy:**  
`tenacity` with `wait_exponential(min=2, max=10)` gives delays of 2s → 4s → 8s before giving up. Failures are isolated per-batch — the job continues.

---

## Scale Considerations

**Current bottlenecks at 100× traffic:**
- Single Celery worker — add more workers with `--concurrency` or horizontal scaling
- PostgreSQL connection pool exhaustion — add `pgBouncer` or increase pool size
- Redis memory — consider Redis Cluster or a managed Redis with eviction policies
- Gemini API rate limits — implement request queuing with a token bucket

**Enterprise re-architecture:**
- Replace Celery+Redis with Kafka for durable, replayable event streaming
- Use async SQLAlchemy + connection pooling via `asyncpg`
- Add a CDN/S3 for CSV uploads instead of local volume mounts
- Kubernetes deployment with horizontal pod autoscaling on worker pods
