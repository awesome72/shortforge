"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Notice, Seg, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
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
  const [photos, setPhotos] = useState<File[]>([]);
  const [kinds, setKinds] = useState<PhotoKind[]>([]);
  // 만들기 전 확인: 맞춤법 제안과 막연한 혜택 되묻기. 한 번 보여 준 뒤에는 그대로 만들 수 있다
  const [fixes, setFixes] = useState<ShopFix[]>([]);
  const [offerAsk, setOfferAsk] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    try {
      const saved = { shop_name: shop.shop_name.trim(), area: shop.area.trim(), action: shop.action.trim() };
      await api.saveShop(saved).catch(() => undefined); // 저장 못 해도 영상은 만든다
      const { id } = await api.create({
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
      });
      try {
        await api.upload(id, photos, true, kinds);
      } catch (e) {
        await api.deleteProject(id).catch(() => undefined); // 사진 없는 프로젝트를 남기지 않는다
        throw e;
      }
      await api.runAll(id, "s1", "s6").catch(() => {}); // 실패하면 화면의 '만들기 시작'으로 이어 간다
      router.push(`/p/${id}`);
    } catch (e) {
      setError((e as Error).message);
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
        <span className="text-[14px] font-semibold">무엇을 알릴까요?</span>
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
      <label className="flex flex-col gap-1.5 text-[14px] font-semibold">
        가게·메뉴 사진
        <input
          type="file"
          multiple
          accept=".jpg,.jpeg,.png,.webp"
          className="text-[13.5px] font-normal text-ink-2"
          onChange={(e) => {
            const files = [...(e.target.files ?? [])];
            setPhotos(files);
            setKinds(files.map(() => "menu"));
          }}
        />
        <span className="text-[12.5px] font-normal text-muted">
          손님에게 실제 모습을 보여 주도록 올린 사진만 써요. 이런 사진이 있으면 장면마다 다른 사진이 나와요:{" "}
          {SHOTS.join(", ")}.
        </span>
      </label>
      {photos.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-[13px] text-ink-2">사진마다 무엇인지 골라 주세요. 대본이 가진 사진에 맞춰 장면을 짜요.</span>
          {photos.map((f, i) => (
            <div key={`${f.name}-${i}`} className="flex flex-wrap items-center gap-2 text-[13px]">
              <span className="min-w-0 max-w-[220px] truncate text-muted">{f.name}</span>
              <Seg
                label={`${f.name} 종류`}
                value={kinds[i] ?? "menu"}
                onChange={(v) => setKinds((ks) => ks.map((k, j) => (j === i ? v : k)))}
                options={PHOTO_KIND}
              />
            </div>
          ))}
        </div>
      )}
      <p className="text-[12.5px] text-muted">
        적은 내용만 대사에 쓰도록 확인해요. 그래도 AI가 쓴 글이니 올리기 전에 대사를 꼭 읽어 주세요.
      </p>
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
            <span className="text-[12.5px] text-muted">
              AI가 맞춤법만 살펴봤어요. 고칠 것이 없으면 그대로 &lsquo;홍보 영상 만들기&rsquo;를 눌러 주세요.
            </span>
          </div>
        </Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" className="min-h-14 px-7 text-[16px]" disabled={!ready || busy || blocked}>
          {busy ? (checked ? "준비 중…" : "확인하는 중…") : "홍보 영상 만들기"}
        </Button>
        {!ready && <span className="text-[13px] text-muted">{needed.join(", ")}을 채워 주세요.</span>}
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
    <label className="flex min-w-0 flex-col gap-1.5 text-[14px] font-semibold">
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
