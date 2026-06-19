import os
from fastapi import FastAPI
from app.api.routes import router
from app.core.config import settings
from app.db.session import engine
from app.db.models import Base

# Create all tables on startup (replaces Alembic for simplicity)
Base.metadata.create_all(bind=engine)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

app = FastAPI(
    title="AI-Powered Transaction Processing Pipeline",
    version="1.0.0",
)

app.include_router(router)

@app.get("/health")
def health():
    return {"status": "ok"}