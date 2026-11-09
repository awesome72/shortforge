"use client";

import { HEIC_ACCEPT, HEIC_HINT, isHeic } from "@/lib/photo";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Button, Notice, Seg, inputClass } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { BusinessBrief, Shop, ShopFix } from "@/lib/types";

const PURPOSE: { value: BusinessBrief["purpose"]; label: string }[] = [
  { value: "new_menu", label: "신메뉴" },
  { value: "promotion", label: "할인·이벤트" },
  { value: "intro", label: "가게 소개" },
  { value: "notice", label: "공지" },
];

type PhotoKind = "menu" | "shop" | "owner" | "other";
const PHOTO_KIND: { value: PhotoKind; label: string }[] = [
  { value: "menu", label: "메뉴·음식" },
  { value: "shop", label: "매장·간판" },
  { value: "owner", label: "사장님·조리 모습" },
  { value: "other", label: "기타" },
];
const PHOTO_EXT = /\.(jpe?g|png|webp)$/i;
const MAX_PHOTO_BYTES = 25 * 1024 * 1024; // 서버 MAX_UPLOAD_BYTES와 같다

// 음식점에서 찍어 두면 좋은 사진 (장면마다 다른 사진이 나오게)
const SHOTS = ["대표 메뉴 가까이", "메뉴 전체가 보이게", "조리하는 손이나 모습", "매장 안", "간판이나 입구"];

/** 소상공인 모드 입력: 가게 정보는 한 번 넣으면 다음부터 채워진다 */
export function BusinessForm({ blocked = false }: { blocked?: boolean }) {
  const router = useRouter();
  const [shops, setShops] = useState<Shop[]>([]);
  const [shop, setShop] = useState<Shop>({ shop_name: "", area: "", action: "" });
  const [purpose, setPurpose] = useState<BusinessBrief["purpose"]>("new_menu");
  const [product, setProduct] = useState("");
  const [offer, setOffer] = useState("");
  const [period, setPeriod] = useState("");
  const [pride, setPride] = useState("");
  // 고른 사진: 미리보기 주소와 종류를 함께 둔다 (더하기·빼기 가능)
  const [photos, setPhotos] = useState<{ file: File; url: string; kind: PhotoKind }[]>([]);
  const photoInput = useRef<HTMLInputElement>(null);
  // 만드는 중 진행 (사진 올리기는 장수가 많으면 몇십 초 걸린다)과 취소
  const [stage, setStage] = useState<string | null>(null);
  const cancelled = useRef(false);
  const uploading = useRef<AbortController | null>(null);
  const [photoError, setPhotoError] = useState<string | null>(null);
  // 만들기 전 확인: 맞춤법 제안과 막연한 혜택 되묻기. 한 번 보여 준 뒤에는 그대로 만들 수 있다
  const [fixes, setFixes] = useState<ShopFix[]>([]);
  const [offerAsk, setOfferAsk] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 미리보기 주소는 화면을 떠날 때 돌려준다
  const urls = useRef<string[]>([]);
  useEffect(() => {
    urls.current = photos.map((p) => p.url);
  }, [photos]);
  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), []);

  const addPhotos = (picked: File[]) => {
    // 올리기 전에 고르는 자리에서 바로 알려 준다 (서버가 거절하면 다시 눌러도 같다)
    const ok = picked.filter((f) => PHOTO_EXT.test(f.name) && f.size <= MAX_PHOTO_BYTES);
    const bad = picked.filter((f) => !ok.includes(f) && !isHeic(f));
    const heic = picked.some(isHeic);
    const msgs = [
      bad.length ? `${bad.map((f) => f.name).join(", ")}: 넣지 않았어요. jpg·png·webp 사진이고 25MB보다 작아야 해요.` : "",
      heic ? HEIC_HINT : "",
    ].filter(Boolean);
    setPhotoError(msgs.length ? msgs.join("\n") : null);
    const fresh = ok.map((file) => ({ file, url: URL.createObjectURL(file), kind: "menu" as PhotoKind }));
    setPhotos((rows) => [...rows, ...fresh]);
  };
  const removePhoto = (i: number) =>
    setPhotos((rows) => {
      URL.revokeObjectURL(rows[i].url);
      return rows.filter((_, j) => j !== i);
    });

  useEffect(() => {
    api
      .shops()
      .then((rows) => {
        setShops(rows);
        if (rows[0]) setShop(rows[0]);
      })
      .catch(() => undefined); // 가게 목록이 없어도 입력해서 시작할 수 있다
  }, []);

  const needed = [
    !shop.shop_name.trim() && "가게 이름",
    !product.trim() && (purpose === "notice" ? "알릴 내용" : "상품"),
    purpose === "promotion" && !offer.trim() && "혜택",
    !shop.action?.trim() && "손님이 할 일",
    !photos.length && "사진",
  ].filter(Boolean);
  const ready = needed.length === 0;

  const values: Record<string, string> = { product, offer, period, pride, action: shop.action };
  const setters: Record<string, (v: string) => void> = {
    product: setProduct,
    offer: setOffer,
    period: setPeriod,
    pride: setPride,
    action: (v) => setShop({ ...shop, action: v }),
  };

  const submit = async () => {
    if (!checked) {
      setBusy(true);
      const result = await api
        .checkShop({ shop_name: shop.shop_name, area: shop.area, purpose, ...values })
        .catch(() => null); // 확인을 못 해도 만들 수 있다
      setChecked(true);
      setBusy(false);
      if (result && (result.fixes.length || result.offer_question)) {
        setFixes(result.fixes);
        setOfferAsk(result.offer_question);
        return;
      }
    }
    await create();
  };

  const applyFix = (fix: ShopFix) => {
    if ((values[fix.field] ?? "").trim() === fix.original) setters[fix.field]?.(fix.fixed);
    setFixes((rows) => rows.filter((f) => f !== fix));
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    cancelled.current = false;
    let id: string | null = null;
    // 취소를 누르면 다음 단계로 가지 않고, 만든 프로젝트는 지운다
    const stopIfCancelled = async () => {
      if (!cancelled.current) return false;
      if (id) {
        await api.cancelRun(id).catch(() => undefined); // 대사 쓰기가 시작됐으면 멈춘다
        for (let i = 0; i < 6; i++) {
          // 멈춘 작업이 정리되기 전이면 409라 잠깐 기다렸다 다시 지운다
          const ok = await api.deleteProject(id).then(
            () => true,
            (e) => !(e instanceof ApiError && e.status === 409),
          );
          if (ok) break;
          await new Promise((r) => setTimeout(r, 500));
        }
      }
      setStage(null);
      setBusy(false);
      return true;
    };
    try {
      const saved = { shop_name: shop.shop_name.trim(), area: shop.area.trim(), action: shop.action.trim() };
      setStage("가게 정보를 저장하는 중");
      await api.saveShop(saved).catch(() => undefined); // 저장 못 해도 영상은 만든다
      if (await stopIfCancelled()) return;
      ({ id } = await api.create({
        topic: "",
        mode: "business",
        business: {
          ...saved,
          category: "restaurant",
          purpose,
          product: product.trim(),
          offer: offer.trim(),
          period: period.trim(),
          pride: pride.trim(),
        },
      }));
      if (await stopIfCancelled()) return;
      setStage(`사진 ${photos.length}장을 올리는 중`);
      uploading.current = new AbortController();
      try {
        await api.upload(
          id,
          photos.map((p) => p.file),
          true,
          photos.map((p) => p.kind),
          uploading.current.signal,
        );
      } catch (e) {
        if (await stopIfCancelled()) return; // 취소로 끊은 것이다
        await api.deleteProject(id).catch(() => undefined); // 사진 없는 프로젝트를 남기지 않는다
        id = null;
        throw e;
      } finally {
        uploading.current = null;
      }
      if (await stopIfCancelled()) return;
      setStage("대사 쓰기를 시작하는 중");
      await api.runAll(id, "s1", "s6").catch(() => {}); // 실패하면 화면의 '만들기 시작'으로 이어 간다
      if (await stopIfCancelled()) return;
      router.push(`/p/${id}`); // 이어지는 진행은 다음 화면이 보여 주고, 거기서도 멈출 수 있다
    } catch (e) {
      // 사진이 거절된 것(413·415)은 다시 눌러도 같다: 그 사진을 빼라고 안내한다
      const photo = e instanceof ApiError && (e.status === 413 || e.status === 415);
      setError(
        photo
          ? `${(e as Error).message}. 그 사진을 빼고 다시 눌러 주세요.`
          : `만들지 못했어요: ${(e as Error).message}. 다시 눌러 주세요.`,
      );
      setStage(null);
      setBusy(false);
    }
  };

  return (
    <form
      className="mt-7 flex max-w-[860px] flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready && !blocked) submit();
      }}
    >
      {shops.length > 1 && (
        <select
          className={inputClass}
          aria-label="저장된 가게"
          value={shop.shop_name}
          onChange={(e) => {
            const found = shops.find((s) => s.shop_name === e.target.value);
            if (found) setShop(found);
          }}
        >
          {shops.map((s) => (
            <option key={s.shop_name} value={s.shop_name}>
              {s.shop_name}
            </option>
          ))}
        </select>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Text label="가게 이름" max={40} value={shop.shop_name} hint="예: 소담 분식" onChange={(v) => setShop({ ...shop, shop_name: v })} />
        <Text label="동네" max={40} value={shop.area} hint="예: 부천 상동" onChange={(v) => setShop({ ...shop, area: v })} />
      </div>
      <div className="flex flex-col gap-1.5">
        <span className="text-md font-semibold">무엇을 알릴까요?</span>
        <Seg label="알릴 내용" value={purpose} onChange={setPurpose} options={PURPOSE} />
      </div>
      <Text label={purpose === "notice" ? "알릴 내용" : "상품"} value={product} hint="예: 김치볶음밥" onChange={setProduct} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Text label={purpose === "promotion" ? "혜택" : "혜택 (있으면)"} value={offer} hint="예: 평일 점심 1,000원 할인" onChange={setOffer} />
        <Text label="기간 (있으면)" max={40} value={period} hint="예: 11월 말까지" onChange={setPeriod} />
      </div>
      <Text label="우리 가게 자랑 (있으면)" value={pride} hint="예: 매일 아침 직접 반죽해요" onChange={setPride} />
      <Text
        label="손님이 할 일"
        max={40}
        value={shop.action}
        hint="예: 네이버 지도에서 소담 분식을 찾아 주세요"
        onChange={(v) => setShop({ ...shop, action: v })}
      />
      <div className="flex flex-col gap-2">
        <span className="text-md font-semibold">가게·메뉴 사진</span>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" variant="ghost" onClick={() => photoInput.current?.click()} disabled={busy}>
            {photos.length ? "사진 더 넣기" : "사진 고르기"}
          </Button>
          <span className="text-sm text-muted">
            {photos.length ? `${photos.length}장 골랐어요` : "아직 고른 사진이 없어요"}
          </span>
          <input
            ref={photoInput}
            type="file"
            multiple
            accept={`.jpg,.jpeg,.png,.webp,${HEIC_ACCEPT}`}
            aria-label="가게·메뉴 사진"
            className="sr-only"
            onChange={(e) => {
              addPhotos([...(e.target.files ?? [])]);
              e.target.value = ""; // 같은 사진을 빼고 다시 고를 수 있게
            }}
          />
        </div>
        {photoError && <span className="text-sm whitespace-pre-line text-err">{photoError}</span>}
        <span className="text-xs text-muted">
          실제 사진만 써요. 추천: {SHOTS.join(", ")}
        </span>
      </div>
      {photos.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-sm text-ink-2">사진마다 무엇인지 골라 주세요. 장면에 맞는 사진을 넣어요.</span>
          {photos.map((p, i) => (
            <div key={p.url} className="flex flex-wrap items-center gap-3 text-sm">
              {/* eslint-disable-next-line @next/next/no-img-element -- 고른 사진 미리보기(브라우저 안의 주소) */}
              <img src={p.url} alt="" className="h-16 w-16 flex-none rounded-ctl border border-line-strong object-cover" />
              <div className="flex min-w-0 flex-col gap-1.5">
                <span className="max-w-[260px] truncate text-muted">{p.file.name}</span>
                <Seg
                  label={`${p.file.name} 종류`}
                  value={p.kind}
                  onChange={(v) => setPhotos((rows) => rows.map((r, j) => (j === i ? { ...r, kind: v } : r)))}
                  options={PHOTO_KIND}
                />
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => removePhoto(i)}
                className="ml-auto rounded-md border border-line-strong px-3 py-1 text-sm text-ink-2 hover:text-ink disabled:opacity-50"
              >
                사진 빼기
              </button>
            </div>
          ))}
        </div>
      )}
      {checked && (fixes.length > 0 || offerAsk) && (
        <Notice tone="warn">
          <div className="flex flex-col gap-2">
            {fixes.map((f) => (
              <div key={f.field} className="flex flex-wrap items-center gap-2">
                <span>
                  {f.label}: &lsquo;{f.original}&rsquo; → &lsquo;{f.fixed}&rsquo;로 고칠까요?
                </span>
                <button type="button" className="font-semibold text-accent" onClick={() => applyFix(f)}>
                  고치기
                </button>
              </div>
            ))}
            {offerAsk && <span>혜택: {offerAsk}</span>}
            <span className="text-xs text-muted">AI가 맞춤법만 봤어요.</span>
          </div>
        </Notice>
      )}
      {stage && (
        <Notice tone="info">
          <div className="flex flex-wrap items-center gap-3">
            <span className="sf-pulse size-2 rounded-full bg-accent" />
            <span className="flex-1">{stage}…</span>
            <button
              type="button"
              className="font-semibold text-muted hover:text-ink"
              onClick={() => {
                cancelled.current = true;
                uploading.current?.abort(); // 올리는 중이면 요청도 끊는다
                setStage("취소하는 중");
              }}
            >
              취소
            </button>
          </div>
        </Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" className="min-h-14 px-7 text-lg" disabled={!ready || busy || blocked}>
          {busy
            ? checked
              ? "만드는 중…"
              : "확인하는 중…"
            : checked // 확인을 마쳤으니 다음 누름은 바로 만든다
              ? "이대로 만들기"
              : "확인하고 만들기"}
        </Button>
        {!ready && <span className="text-sm text-muted">{needed.join(", ")}을 채워 주세요.</span>}
      </div>
    </form>
  );
}

function Text({
  label,
  value,
  hint,
  onChange,
  max = 80,
}: {
  label: string;
  value: string;
  hint: string;
  onChange: (v: string) => void;
  max?: number; // 서버의 BusinessBrief 길이와 같게
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5 text-md font-semibold">
      {label}
      <input
        className={`${inputClass} font-normal`}
        value={value}
        placeholder={hint}
        maxLength={max}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
