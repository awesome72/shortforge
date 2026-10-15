# ShortForge 웹 UI (Next.js 16)

7단계 워크스페이스. 백엔드(FastAPI)와 같은 Project JSON을 읽고 쓰며, 진행은 SSE로 받는다.

```bash
# 1) 백엔드 (shortforge/backend) — Gemini 키 없이 UI만 볼 때는 DEV_FAKE_LLM=true
DEV_FAKE_LLM=true uv run uvicorn app.main:app --port 8000 --reload

# 2) 프론트엔드 (이 폴더)
npm install
npm run dev            # http://localhost:3000
npx tsc --noEmit && npm run lint
```

- API 주소는 `NEXT_PUBLIC_API_BASE`(기본 `http://127.0.0.1:8000`). 백엔드 CORS 허용 목록은 `CORS_ORIGINS`.
- 타입(`lib/types.ts`)은 `backend/app/schemas/project.py`와 같은 모양이다. 계약이 바뀌면 함께 바꾼다.
- 화면 설계 원본: 저장소 루트의 `ShortForge 숏폼 스튜디오.html` 목업.
