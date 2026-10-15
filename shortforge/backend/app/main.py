"""FastAPI 엔트리. 나머지 엔드포인트(PROJECT_PROMPT §8)는 Step 6에서 채운다."""

from fastapi import FastAPI

from app.config import settings
from app.quota import QuotaMeter

app = FastAPI(title="ShortForge", version="0.0.1")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_mode": settings.llm_mode, "image_mode": settings.image_mode}


@app.get("/quota")
def quota() -> dict:
    """오늘(PT 기준) YouTube units 사용량. 상단 쿼터 미터용 (F-2.4)."""
    return QuotaMeter(settings.db_path, settings.youtube_daily_unit_limit).summary()
