"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Notice, Seg, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import type { BusinessBrief, Shop } from "@/lib/types";

const PURPOSE: { value: BusinessBrief["purpose"]; label: string }[] = [
  { value: "new_menu", label: "신메뉴" },
  { value: "promotion", label: "할인·이벤트" },
  { value: "intro", label: "가게 소개" },
  { value: "notice", label: "공지" },
];

/** 소상공인 모드 입력: 가게 정보는 한 번 넣으면 다음부터 채워진다 */
export function BusinessForm() {
  const router = useRouter();
  const [shops, setShops] = useState<Shop[]>([]);
  const [shop, setShop] = useState<Shop>({ shop_name: "", area: "", action: "" });
  const [purpose, setPurpose] = useState<BusinessBrief["purpose"]>("new_menu");
  const [product, setProduct] = useState("");
  const [offer, setOffer] = useState("");
  const [period, setPeriod] = useState("");
  const [pride, setPride] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
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
        await api.upload(id, photos);
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
        if (ready) create();
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
          onChange={(e) => setPhotos([...(e.target.files ?? [])])}
        />
        <span className="text-[12.5px] font-normal text-muted">
          손님에게 실제 모습을 보여 주도록 올린 사진만 써요. 사진이 장면보다 적으면 돌려 가며 넣어요. 3장 이상을 권해요.
        </span>
      </label>
      <p className="text-[12.5px] text-muted">
        적은 내용만 대사에 쓰도록 확인해요. 그래도 AI가 쓴 글이니 올리기 전에 대사를 꼭 읽어 주세요.
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" className="min-h-14 px-7 text-[16px]" disabled={!ready || busy}>
          {busy ? "준비 중…" : "홍보 영상 만들기"}
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
