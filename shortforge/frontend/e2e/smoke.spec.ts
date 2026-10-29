import { expect, test, type Page } from "@playwright/test";

// Fake 렌더는 영상 파일을 만들지 않고, Fake 인기 영상 썸네일 주소도 없으므로 리소스 404는 오류로 치지 않는다
function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  return errors;
}

const TOPIC = "예: 퇴근 후 10분 홈트로 3개월간 바뀐 점";

test("인기 영상을 크게 보고 '이런 영상 만들기'로 주제를 채운다", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "요즘 많이 보는 영상" })).toBeVisible();
  const cards = page.getByRole("button", { name: /크게 보기$/ });
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThanOrEqual(10);
  await cards.first().click();
  await expect(page.getByRole("dialog").locator("iframe")).toBeVisible(); // 내려받지 않고 YouTube 플레이어로
  await page.getByRole("button", { name: "이런 영상 만들기" }).click();
  await expect(page.getByPlaceholder(TOPIC)).not.toHaveValue("");
  expect(errors).toEqual([]);
});

test("세 단계로 아이디어 → 다듬기(바로 반영) → 완성", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/");
  await page.getByPlaceholder(TOPIC).fill("퇴근 후 10분 홈트");
  await page.getByRole("button", { name: "만들기", exact: true }).click();
  await expect(page).toHaveURL(/\/p\/prj_[0-9a-f]{12}$/);

  // ① 아이디어는 자동으로 끝나고 ② 다듬기로 넘어간다
  const finish = page.getByRole("button", { name: /영상 완성하기/ });
  await expect(finish).toBeEnabled({ timeout: 60_000 });
  await expect(page.getByText("S1")).toHaveCount(0); // 내부 단계 이름을 보이지 않는다

  // 대사를 고치면 그 장면만 다시 만들어 반영한다
  const first = page.locator("textarea").first();
  await first.fill("고친 첫 대사로 시작해요");
  const saved = page.waitForResponse((r) => r.url().includes("/line") && r.request().method() === "POST");
  await first.blur();
  expect((await saved).status()).toBe(200);
  await expect(finish).toBeEnabled({ timeout: 30_000 });
  await expect(page.locator("textarea").first()).toHaveValue("고친 첫 대사로 시작해요");

  // 음악을 바꾸면 바로 반영된다
  const calm = page.getByRole("group", { name: "배경음악" }).getByRole("button").first();
  await calm.click();
  await expect(calm).toHaveAttribute("aria-pressed", "true", { timeout: 30_000 });

  // 장면 하나만 내 사진으로 바꾸면 장면 순서 맞추기를 바로 다시 해 미리보기에 반영한다
  const PNG = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64",
  );
  const patched = page.waitForResponse((r) => r.url().endsWith("/assets") && r.request().method() === "PATCH");
  await page
    .getByText("내 사진")
    .first()
    .locator("input[type=file]")
    .setInputFiles({ name: "mine.png", mimeType: "image/png", buffer: PNG });
  expect((await patched).status()).toBe(200);
  await expect(finish).toBeEnabled({ timeout: 30_000 });

  // ③ 완성
  await finish.click();
  await expect(page.getByText("업로드 전 체크리스트")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("link", { name: "영상 내려받기" })).toBeVisible();

  // 전문가 화면은 그대로 남아 있다
  await page.getByRole("link", { name: "전문가 화면" }).click();
  await expect(page).toHaveURL(/\/pro$/);
  await expect(page.getByRole("link", { name: "쉬운 화면" })).toBeVisible(); // 다 뜬 뒤 단축키
  await page.keyboard.press("7");
  await expect(page.getByRole("heading", { name: "렌더 결과" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("휴대폰 폭에서 옆으로 넘치지 않는다", async ({ page }) => {
  const errors = collectErrors(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "요즘 많이 보는 영상" })).toBeVisible();
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(await overflow()).toBe(false);
  await page.getByPlaceholder(TOPIC).fill("아침 루틴");
  await page.getByRole("button", { name: "만들기", exact: true }).click();
  await expect(page).toHaveURL(/\/p\/prj_/);
  await expect(page.getByRole("button", { name: /영상 완성하기/ })).toBeVisible({ timeout: 60_000 });
  expect(await overflow()).toBe(false);
  expect(errors).toEqual([]);
});
