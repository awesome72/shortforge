import { expect, test, type Page } from "@playwright/test";

// Fake 렌더는 영상 파일을 만들지 않으므로 미디어 404는 오류로 치지 않는다
function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  return errors;
}

test("새 프로젝트를 만들어 전체 실행하고 단계 화면을 본다", async ({ page }) => {
  const errors = collectErrors(page);

  await page.goto("/");
  await page.getByPlaceholder("예: 퇴근 후 10분 홈트로 3개월간 바뀐 점").fill("퇴근 후 10분 홈트");
  await page.getByPlaceholder("예: 30대 직장인").fill("30대 직장인");
  await page.getByRole("button", { name: "새 프로젝트 시작" }).click();
  await expect(page).toHaveURL(/\/p\/prj_[0-9a-f]{12}/);

  await page.getByRole("button", { name: /전체 파이프라인 실행/ }).click();
  await expect(page.getByRole("button", { name: /모두 완료/ })).toBeVisible({ timeout: 60_000 });

  // 5단계: 장면 카드와 사진·영상 교체
  await page.keyboard.press("5");
  await expect(page.locator("article").first()).toBeVisible();
  expect(await page.locator("article").count()).toBeGreaterThanOrEqual(5);
  await expect(page.getByText("사진·영상 교체").first()).toBeVisible();

  // 7단계: 렌더 결과·내보내기 전 점검·업로드 체크리스트·커버 문구
  await page.keyboard.press("7");
  await expect(page.getByRole("heading", { name: "렌더 결과" })).toBeVisible();
  await expect(page.getByText("내보내기 전 점검")).toBeVisible();
  await expect(page.getByText("업로드 전 체크리스트")).toBeVisible();
  await expect(page.getByPlaceholder("예: 은퇴 후 30년 / 두 번째 인생 지도")).toBeVisible();

  expect(errors).toEqual([]);
});

test("작업 화면이 휴대폰 폭에서 옆으로 넘치지 않는다", async ({ page }) => {
  const errors = collectErrors(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByPlaceholder("예: 퇴근 후 10분 홈트로 3개월간 바뀐 점").fill("아침 루틴");
  await page.getByRole("button", { name: "새 프로젝트 시작" }).click();
  await expect(page).toHaveURL(/\/p\/prj_/);
  await expect(page.getByRole("heading").first()).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
  expect(errors).toEqual([]);
});
