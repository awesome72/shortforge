import os from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

// 화면 자동 테스트: 모든 어댑터를 Fake로 둔 API(DEV_FAKE_ALL)와 프로덕션 빌드(next start)를 띄워
// 새 프로젝트 → 전체 실행 → 단계 화면을 실제 브라우저로 확인한다. 키·FFmpeg·네트워크가 필요 없다.
// 브라우저는 Windows에 깔린 Edge를 쓴다(브라우저를 따로 내려받지 않는다).
// 웹 빌드의 API 주소(NEXT_PUBLIC_API_BASE)는 빌드할 때 정해지므로, 포트를 바꾸면 그 주소로 빌드한다.
const API_PORT = Number(process.env.E2E_API_PORT ?? 8000);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3000);
const DATA_DIR = path.join(os.tmpdir(), `shortforge-e2e-${process.pid}`);

export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: { baseURL: `http://localhost:${WEB_PORT}`, channel: "msedge" },
  webServer: [
    {
      command: `uv run uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${API_PORT}/health`,
      timeout: 180_000,
      env: {
        DEV_FAKE_ALL: "true",
        LLM_ADVANCED: "off",
        DATA_DIR,
        CORS_ORIGINS: JSON.stringify([`http://localhost:${WEB_PORT}`, `http://127.0.0.1:${WEB_PORT}`]),
      },
    },
    {
      command: `npx next start -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      timeout: 180_000,
    },
  ],
});
