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

test("인기 영상을 크게 보고 '이 주제로 채우기'로 주제를 채운다", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "요즘 많이 보는 영상" })).toBeVisible();
  const cards = page.getByRole("button", { name: /크게 보기$/ });
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThanOrEqual(10);
  await cards.first().click();
  await expect(page.getByRole("dialog").locator("iframe")).toBeVisible(); // 내려받지 않고 YouTube 플레이어로
  await page.getByRole("button", { name: "이 주제로 채우기" }).click();
  await expect(page.getByPlaceholder(TOPIC)).not.toHaveValue("");
  expect(errors).toEqual([]);
});

test("세 단계로 아이디어 → 다듬기(바로 반영) → 완성", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/");
  await page.getByPlaceholder(TOPIC).fill("퇴근 후 10분 홈트");
  await page.getByRole("button", { name: /^영상 만들기 시작/ }).click();
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

  // 대사를 이어서 고치면 다음 칸이 잠기지 않고 차례로 저장한다
  const second = page.locator("textarea").nth(1);
  const third = page.locator("textarea").nth(2);
  await second.fill("둘째 대사도 고쳤어요");
  await second.press("Tab"); // 저장이 시작돼도 키보드 커서가 사라지지 않는다
  await expect(page.locator("body")).not.toBeFocused();
  await third.click();
  await expect(third).toBeEnabled();
  await third.fill("셋째 대사도 고쳤어요");
  await page.locator("textarea").first().click(); // 칸을 벗어나 저장한다
  await expect(finish).toBeEnabled({ timeout: 30_000 });
  await expect(page.locator("textarea").nth(1)).toHaveValue("둘째 대사도 고쳤어요");
  await expect(page.locator("textarea").nth(2)).toHaveValue("셋째 대사도 고쳤어요");

  // 아이디어 화면에서 대사를 먼저 볼 수 있다
  await page.getByRole("button", { name: /아이디어/ }).click();
  await expect(page.getByRole("heading", { name: "이렇게 말할 거예요" })).toBeVisible();
  await expect(page.getByRole("button", { name: "이 아이디어로 바꾸기" }).first()).toBeVisible();
  await page.getByRole("button", { name: "다듬기로 가기 →" }).click(); // 다 끝난 아이디어 화면의 주 버튼

  // 장면 하나만 내 사진으로 바꾸면 서버가 그 장면만 지시서에 반영한다
  const PNG = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64",
  );
  const patched = page.waitForResponse((r) => r.url().endsWith("/photo") && r.request().method() === "POST");
  await page
    .getByText("내 사진 넣기")
    .first()
    .locator("input[type=file]")
    .setInputFiles({ name: "mine.png", mimeType: "image/png", buffer: PNG });
  expect((await patched).status()).toBe(200);
  await expect(finish).toBeEnabled({ timeout: 30_000 });

  // ③ 완성
  await finish.click();
  await expect(page.getByText("업로드 전 체크리스트")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("link", { name: "영상 내려받기" })).toBeVisible();

  // 완성 뒤 대사를 고쳐도 지난 영상은 보이고 받을 수 있다 (다시 만들기 전)
  await page.getByRole("button", { name: /^2\s*다듬기$/ }).click();
  const line = page.locator("textarea").first();
  await line.fill("완성 뒤에 고친 대사예요");
  const relined = page.waitForResponse((r) => r.url().includes("/line") && r.request().method() === "POST");
  await line.blur();
  expect((await relined).status()).toBe(200);
  await page.getByRole("button", { name: /^3\s*완성$/ }).click();
  await expect(page.getByText("지난 영상이에요")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("link", { name: "영상 내려받기" })).toBeVisible();
  await expect(page.getByText("영상이 완성됐어요")).toHaveCount(0);

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
  await page.getByRole("button", { name: /^영상 만들기 시작/ }).click();
  await expect(page).toHaveURL(/\/p\/prj_/);
  await expect(page.getByRole("button", { name: /영상 완성하기/ })).toBeVisible({ timeout: 60_000 });
  expect(await overflow()).toBe(false);
  // 장면 그림을 누르면 그 장면 도구가 아래에서 올라오고, Esc로 닫힌다
  await page.getByRole("button", { name: "장면 1 그림 도구 열기" }).click();
  const sheet = page.getByRole("dialog", { name: "장면 1 도구" });
  await expect(sheet.getByText("내 사진 넣기")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  // 미리보기는 아래 막대의 버튼으로 크게 열고 닫는다
  await page.getByRole("button", { name: "미리보기", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "미리보기" });
  await expect(preview).toBeVisible();
  await preview.getByRole("button", { name: "닫기" }).click();
  await expect(preview).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("설정: 기본값 '자동'에서도 그림 키 칸이 보이고 휴대폰 폭에서 넘치지 않는다", async ({ page }) => {
  const errors = collectErrors(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/settings");
  await expect(page.getByRole("radio").first()).toBeVisible();
  // 자동은 키가 있는 소스를 모두 쓴다. 이 칸이 안 보여 첫 사용자가 키를 넣을 곳이 없었다
  // 이미 설정된 키는 한 줄로 접힌다 (개발 PC의 .env에 키가 있으면): 입력칸이나 '바꾸기' 중 하나
  await expect(
    page.getByLabel("Cloudflare API 토큰").or(page.getByRole("button", { name: "Cloudflare API 토큰 바꾸기" })),
  ).toBeVisible();
  await expect(
    page.getByLabel(/Pixabay/).or(page.getByRole("button", { name: /Pixabay.*바꾸기/ })).first(),
  ).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  // 화면 밝기: 밝게를 고르면 바로 바뀌고, 새로고침해도 그대로다 (그리기 전에 적용)
  await page.getByRole("group", { name: "화면 밝기" }).getByRole("button", { name: "밝게" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe("rgb(243, 244, 246)");
  await page.getByRole("group", { name: "화면 밝기" }).getByRole("button", { name: "어둡게" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  // 상단 바 버튼은 어둡게 → 밝게 → 시스템 따라. 시스템 따라는 브라우저 설정을 따른다
  const toggle = page.getByRole("button", { name: /^화면 밝기:/ });
  await toggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await toggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "system");
  await page.emulateMedia({ colorScheme: "light" });
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe("rgb(243, 244, 246)");
  await page.emulateMedia({ colorScheme: "dark" });
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe("rgb(11, 13, 17)");
  await toggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(errors).toEqual([]);
});

test("우리 가게 홍보는 올린 사진만 쓰고 혜택을 그대로 넣는다", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "우리 가게 홍보" }).click();
  await page.getByLabel("가게 이름").fill("소담 분식");
  await page.getByLabel("동네").fill("부천 상동");
  await page.getByLabel("상품").fill("떡복기");
  await page.getByLabel("혜택 (있으면)").fill("평일 점심 1,000원 할인");
  await page.getByLabel("기간 (있으면)").fill("11월 말까지");
  await page.getByLabel("손님이 할 일").fill("네이버 지도에서 찾아 주세요");
  const PNG = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64",
  );
  // 사진은 보이는 버튼으로 고르고, 미리보기를 보고 뺄 수 있다
  await expect(page.getByRole("button", { name: "사진 고르기" })).toBeVisible();
  const photo = { name: "menu.png", mimeType: "image/png", buffer: PNG };
  await page.locator("input[type=file]").setInputFiles([photo, { ...photo, name: "extra.png" }]);
  await expect(page.getByText("2장 골랐어요")).toBeVisible();
  await page.getByRole("button", { name: "빼기" }).last().click();
  await expect(page.getByText("1장 골랐어요")).toBeVisible();
  await expect(page.getByRole("button", { name: "메뉴·음식" })).toHaveAttribute("aria-pressed", "true"); // 사진 종류
  // 만들기 전에 맞춤법을 제안하고, 누를 때만 고친다
  await page.getByRole("button", { name: "확인하고 만들기" }).click();
  await expect(page.getByText(/떡복기. → .떡볶이.로 고칠까요/)).toBeVisible();
  await page.getByRole("button", { name: "고치기" }).click();
  await expect(page.getByLabel("상품")).toHaveValue("떡볶이");
  await page.getByRole("button", { name: "이대로 만들기" }).click();
  await expect(page).toHaveURL(/\/p\/prj_[0-9a-f]{12}$/);

  const finish = page.getByRole("button", { name: /영상 완성하기/ });
  await expect(finish).toBeEnabled({ timeout: 60_000 });
  const lines = await page.locator("textarea").evaluateAll((all) => all.map((t) => (t as HTMLTextAreaElement).value));
  expect(lines).toContain("평일 점심 1,000원 할인! 11월 말까지.");
  expect(lines.at(-1)).toBe("네이버 지도에서 찾아 주세요.");
  await expect(page.getByRole("button", { name: "다른 그림" })).toHaveCount(0); // AI 그림을 쓰지 않는다

  await finish.click();
  await expect(page.getByText("업로드 전 체크리스트")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/가격·혜택·기간이 실제와 같다/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("실패 화면: 지난 영상은 남고, 참고 영상이 없으면 검색어·주제를 그 자리에서 고친다", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/");
  await page.getByPlaceholder(TOPIC).fill("주말 캠핑 준비");
  await page.getByRole("button", { name: /^영상 만들기 시작/ }).click();
  await expect(page).toHaveURL(/\/p\/prj_[0-9a-f]{12}$/);
  const finish = page.getByRole("button", { name: /영상 완성하기/ });
  await expect(finish).toBeEnabled({ timeout: 60_000 });
  await finish.click();
  await expect(page.getByRole("link", { name: "영상 내려받기" })).toBeVisible({ timeout: 60_000 });

  // Fake 어댑터는 실패하지 않으므로 프로젝트 응답만 실패 상태로 바꿔 화면을 본다
  let fail: { step: string; kind: string } = { step: "s7", kind: "render_stall" };
  await page.route(/\/projects\/prj_[0-9a-f]{12}$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const res = await route.fetch();
    const body = await res.json();
    body.status[fail.step] = "error";
    body.errors = { ...body.errors, [fail.step]: "테스트로 넣은 오류" };
    body.error_kinds = { ...body.error_kinds, [fail.step]: fail.kind };
    await route.fulfill({ response: res, json: body });
  });

  await page.reload();
  await page.getByRole("button", { name: /^3\s*완성$/ }).click();
  await expect(page.getByText("영상을 합치다가 멈췄어요")).toBeVisible();
  await expect(page.getByText("지난 영상이에요. 다시 완성하다 멈췄어요")).toBeVisible();
  await expect(page.getByRole("link", { name: "영상 내려받기" })).toBeVisible();
  await expect(page.getByText("문제 보고용 파일 받기")).toBeAttached();

  fail = { step: "s2", kind: "no_refs" };
  await page.reload();
  await expect(page.getByText("주제에 맞는 참고 영상을 찾지 못했어요")).toBeVisible();
  await expect(page.getByRole("button", { name: "검색어 바꿔 다시 찾기" })).toBeVisible();
  await page.getByRole("button", { name: "주제 고치기" }).click();
  await expect(page.getByLabel("새 주제")).toHaveValue("주말 캠핑 준비");
  await expect(page.getByRole("button", { name: /바꾸고 처음부터 다시/ })).toBeDisabled(); // 그대로면 누를 수 없다
  expect(errors).toEqual([]);
});

test("부동산 매물 홍보는 실제 사진과 적은 매물 정보를 그대로 쓴다", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "부동산 매물 홍보" }).click();
  const fill = async (label: string, value: string) => page.getByLabel(label, { exact: true }).fill(value);
  await fill("사무소 이름", "상동 행복공인중개사사무소");
  await fill("대표 공인중개사", "홍길동");
  await fill("사무소 소재지", "부천시 상동 123");
  await fill("연락처", "032-123-4567");
  await fill("등록번호", "41190-2020-00012");
  await fill("손님이 할 일", "문자로 방문 예약해 주세요");
  await fill("가격", "3억 2천만원");
  await fill("소재지 (공개할 범위)", "부천시 상동");
  await fill("면적", "전용 84.9㎡");
  await fill("층 / 총 층수", "7층 / 15층");
  await fill("방향 (기준 포함)", "거실 기준 남향");
  await fill("방·욕실 수", "방 3 · 욕실 2");
  await fill("사용승인일", "2015.03");
  await fill("입주 가능일", "즉시");
  await fill("주차", "세대당 1대");
  await fill("관리비", "월 15만원");
  const PNG = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64",
  );
  await page.getByLabel("매물 사진").setInputFiles({ name: "living.png", mimeType: "image/png", buffer: PNG });
  const make = page.getByRole("button", { name: "매물 영상 만들기" });
  await expect(make).toBeDisabled(); // 사진 공간·개인정보 확인 전
  await page.getByRole("group", { name: "living.png 공간" }).getByRole("button", { name: "거실" }).click();
  await page.getByLabel(/개인정보가 보이지 않아요/).check();
  await make.click();
  await expect(page).toHaveURL(/\/p\/prj_[0-9a-f]{12}$/);

  const finish = page.getByRole("button", { name: /영상 완성하기/ });
  await expect(finish).toBeEnabled({ timeout: 60_000 });
  const lines = await page.locator("textarea").evaluateAll((all) => all.map((t) => (t as HTMLTextAreaElement).value));
  expect(lines).toContain("전세 3억 2천만원. 입주는 즉시 가능해요.");
  expect(lines.at(-1)).toBe("문자로 방문 예약해 주세요.");
  await expect(page.getByRole("button", { name: /다른 그림/ })).toHaveCount(0); // AI 그림을 쓰지 않는다

  // 만든 뒤 가격 오타를 고치면 가격 대사만 바꾼다
  await page.getByRole("button", { name: "매물 정보 고치기" }).click();
  // 앞 화면의 입력 양식이 숨은 채 남아 있어(Next 16) 보이는 칸만 고른다
  await page.getByRole("textbox", { name: "가격", exact: true }).fill("3억 1천만원");
  await page.getByRole("button", { name: "저장하기" }).click();
  await expect(page.locator("textarea").filter({ hasText: "3억 1천만원" })).toHaveCount(1, { timeout: 60_000 });
  await expect(finish).toBeEnabled({ timeout: 60_000 });

  await finish.click();
  await expect(page.getByText("업로드 전 체크리스트")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("계약이 되면 영상을 바로 내린다", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("유료 AI로 움직이기는 금액을 보여 주고 0.9초 뒤에야 시작할 수 있다", async ({ page }) => {
  const errors = collectErrors(page);
  // 화면 테스트 서버는 영상 만들기를 끈다(VIDEO_GEN=off). 유료 방식이 켜진 것처럼 /config만 바꾼다
  await page.route("**/config", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.video_gen = {
      mode: "hf", free: false, label: "LTX-2", usd_per_sec: 0.0128, usd_per_frame: 0.000512, fps: 25,
      budget_usd: 3, spend: { day_utc: "2026-11-09", used_usd: 0, budget_usd: 3 },
    };
    await route.fulfill({ response: res, json: body });
  });
  let calls = 0; // 실제로는 아무것도 만들지 않는다 (돈이 나가는 호출이 몇 번 갔는지만 센다)
  await page.route("**/motion*", async (route) => {
    calls += 1;
    await route.fulfill({ status: 200, json: { project: null, usd: 0 } });
  });
  await page.goto("/");
  await page.getByPlaceholder(TOPIC).fill("주말 베란다 텃밭");
  await page.getByRole("button", { name: /^영상 만들기 시작/ }).click();
  await expect(page.getByRole("button", { name: /영상 완성하기/ })).toBeEnabled({ timeout: 60_000 });

  const move = page.getByRole("button", { name: "장면 1 AI로 움직이기" });
  await move.click();
  const ask = page.getByRole("group", { name: /AI로 움직일까요/ });
  const start = ask.getByRole("button", { name: /쓰고 시작/ });
  await expect(ask.getByText(/^\$\d+\.\d{2}$/)).toBeVisible(); // 금액
  await expect(start).toBeDisabled(); // 습관적인 두 번 누르기로 바로 시작하지 않는다
  await expect(start).toBeEnabled({ timeout: 3_000 });
  await ask.getByRole("button", { name: "취소" }).click();
  await expect(ask).toHaveCount(0);
  expect(calls).toBe(0);

  await move.click();
  await expect(start).toBeEnabled({ timeout: 3_000 });
  await start.click();
  await expect.poll(() => calls).toBe(1);
  expect(errors).toEqual([]);
});
