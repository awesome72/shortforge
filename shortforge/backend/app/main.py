"""FastAPI 엔트리. 엔드포인트(PROJECT_PROMPT §8)는 Step 1·6에서 채운다."""

from fastapi import FastAPI

from app.config import settings

app = FastAPI(title="ShortForge", version="0.0.1")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_mode": settings.llm_mode, "image_mode": settings.image_mode}
