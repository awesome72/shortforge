"use client";

import { HEIC_ACCEPT, HEIC_HINT, isHeic } from "@/lib/photo";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Button, Details, Notice, Seg, inputClass } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { ListingBrief, Office } from "@/lib/types";

// 공인중개사법 제18조의2: 표시·광고에는 중개사무소·개업공인중개사와 매물의 정해진 항목을 밝혀야 한다.
// 그래서 매물 정보 칸은 모두 채워야 만들 수 있고, 값은 대사·끝 화면 카드·설명란에 그대로 나간다.
export const PROPERTY: { value: ListingBrief["prop_type"]; label: string }[] = [
  { value: "apartment", label: "아파트" },
  { value: "officetel", label: "오피스텔" },
  { value: "villa", label: "빌라" },
  { value: "oneroom", label: "원룸" },
];
export const DEAL: { value: ListingBrief["deal"]; label: string }[] = [
  { value: "sale", label: "매매" },
  { value: "jeonse", label: "전세" },
  { value: "monthly", label: "월세" },
];

type Kind = "exterior" | "living" | "kitchen" | "room" | "bath" | "view" | "plan";
const PHOTO_KIND: { value: Kind; label: string }[] = [
  { value: "living", label: "거실" },
  { value: "room", label: "방" },
  { value: "kitchen", label: "주방" },
  { value: "bath", label: "욕실" },
  { value: "view", label: "창밖" },
  { value: "exterior", label: "외관" },
  { value: "plan", label: "평면도" },
];
const PHOTO_EXT = /\.(jpe?g|png|webp)$/i;
const MAX_PHOTO_BYTES = 25 * 1024 * 1024;

const EMPTY_OFFICE: Office = {
  office_name: "",
  office_address: "",
  office_phone: "",
  agent_name: "",
  reg_no: "",
  action: "",
};

// 매물 칸: 이름, 안내, 길이(서버 ListingBrief와 같게)
export const FIELDS: { key: keyof ListingBrief; label: string; hint: string; max: number; need: boolean }[] = [
  { key: "price", label: "가격", hint: "의뢰받은 가격 그대로. 예: 3억 2천만원 / 보증금 1천만원·월 60만원", max: 40, need: true },
  { key: "location", label: "소재지 (공개할 범위)", hint: "예: 부천시 상동", max: 60, need: true },
  { key: "complex_name", label: "단지·건물 이름 (있으면)", hint: "예: 푸른마을", max: 40, need: false },
  { key: "area", label: "면적", hint: "공부상 면적. 예: 전용 84.9㎡", max: 30, need: true },
  { key: "floor", label: "층 / 총 층수", hint: "예: 7층 / 15층", max: 20, need: true },
  { key: "direction", label: "방향 (기준 포함)", hint: "예: 거실 기준 남향", max: 20, need: true },
  { key: "rooms", label: "방·욕실 수", hint: "예: 방 3 · 욕실 2", max: 20, need: true },
  { key: "approved", label: "사용승인일", hint: "예: 2015.03", max: 20, need: true },
  { key: "move_in", label: "입주 가능일", hint: "예: 즉시 / 12월 중순 협의", max: 20, need: true },
  { key: "parking", label: "주차", hint: "예: 세대당 1대", max: 20, need: true },
  { key: "maint_fee", label: "관리비", hint: "최근 평균. 예: 월 15만원", max: 40, need: true },
];

/** 매물 홍보 입력: 중개사무소 정보는 한 번 넣으면 다음 매물부터 채워진다 */
export function ListingForm({ blocked = false }: { blocked?: boolean }) {
  const router = useRouter();
  const [offices, setOffices] = useState<Office[]>([]);
  const [office, setOffice] = useState<Office>(EMPTY_OFFICE);
  const [delArmed, setDelArmed] = useState(false); // 저장한 사무소 지우기: 한 번 더 눌러 확인
  const [propType, setPropType] = useState<ListingBrief["prop_type"]>("apartment");
  const [deal, setDeal] = useState<ListingBrief["deal"]>("jeonse");
  const [facts, setFacts] = useState<Record<string, string>>({});
  const [highlights, setHighlights] = useState("");
  const [nearby, setNearby] = useState("");
  const [privacy, setPrivacy] = useState(false); // 사진에 개인정보가 없는지 한 번 확인
  // 공간은 꼭 고르게 한다: 기본값을 거실로 두면 대사가 '거실 N장'만 알고 대사와 사진이 어긋났다
  const [photos, setPhotos] = useState<{ file: File; url: string; kind: Kind | null }[]>([]);
  const photoInput = useRef<HTMLInputElement>(null);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const cancelled = useRef(false);
  const uploading = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 입력을 세 덩어리로 접는다 (E8): ① 사무소 ② 매물 ③ 사진. 자유롭게 열고, 다 채우면 다음 덩어리가 열린다
  const [open, setOpen] = useState<Record<Group, boolean>>({ office: true, facts: false, photos: false });
  const officeDone = OFFICE_NEED.every((k) => office[k].trim());
  const factsFilled = FIELDS.filter((f) => f.need && (facts[f.key] ?? "").trim()).length;
  const factsNeed = FIELDS.filter((f) => f.need).length;
  const factsDone = factsFilled === factsNeed;
  const [prev, setPrev] = useState({ office: officeDone, facts: factsDone });
  if (prev.office !== officeDone || prev.facts !== factsDone) {
    // 렌더 중 상태 맞추기: 막 다 채운 덩어리의 다음을 연다 (지금 덩어리는 닫지 않는다: 입력 중에 사라지지 않게)
    setPrev({ office: officeDone, facts: factsDone });
    setOpen((o) => ({
      ...o,
      ...(officeDone && !prev.office ? { facts: true } : {}),
      ...(factsDone && !prev.facts ? { photos: true } : {}),
    }));
  }
  const toggle = (g: Group) => setOpen((o) => ({ ...o, [g]: !o[g] }));

  const urls = useRef<string[]>([]);
  useEffect(() => {
    urls.current = photos.map((p) => p.url);
  }, [photos]);
  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), []);

  useEffect(() => {
    api
      .offices()
      .then((rows) => {
        setOffices(rows);
        if (rows[0]) {
          setOffice(rows[0]);
          setOpen((o) => ({ ...o, office: false, facts: true })); // 저장된 사무소는 한 줄로 접는다
        }
      })
      .catch(() => undefined);
  }, []);

  const addPhotos = (picked: File[]) => {
    const ok = picked.filter((f) => PHOTO_EXT.test(f.name) && f.size <= MAX_PHOTO_BYTES);
    const bad = picked.filter((f) => !ok.includes(f) && !isHeic(f));
    const msgs = [
      bad.length ? `${bad.map((f) => f.name).join(", ")}: 넣지 않았어요. jpg·png·webp 사진이고 25MB보다 작아야 해요.` : "",
      picked.some(isHeic) ? HEIC_HINT : "",
    ].filter(Boolean);
    setPhotoError(msgs.length ? msgs.join("\n") : null);
    const fresh = ok.map((file) => ({ file, url: URL.createObjectURL(file), kind: null as Kind | null }));
    setPhotos((rows) => [...rows, ...fresh]);
  };
  const removePhoto = (i: number) =>
    setPhotos((rows) => {
      URL.revokeObjectURL(rows[i].url);
      return rows.filter((_, j) => j !== i);
    });

  const needed = [
    !office.office_name.trim() && "사무소 이름",
    !office.office_address.trim() && "사무소 소재지",
    !office.office_phone.trim() && "연락처",
    !office.agent_name.trim() && "대표 공인중개사",
    !office.reg_no.trim() && "등록번호",
    ...FIELDS.filter((f) => f.need && !(facts[f.key] ?? "").trim()).map((f) => f.label.replace(/ \(.*\)$/, "")),
    !photos.length && "사진",
    photos.some((p) => !p.kind) && "사진마다 공간",
    photos.length > 0 && !privacy && "사진 개인정보 확인",
  ].filter(Boolean) as string[];
  const ready = needed.length === 0;
  const fact = (k: string) => (facts[k] ?? "").trim();
  const formatHints = [
    fact("price") && !/[원억만]/.test(fact("price")) && "가격에 단위(억·만 원)가 없어요",
    fact("area") && !/(㎡|m²|m2|제곱미터)/i.test(fact("area")) && "면적은 ㎡로 적어 주세요(평만 적지 않기)",
    fact("floor") && !/층/.test(fact("floor")) && "층에 '층'을 붙여 주세요",
    fact("direction") && !/향/.test(fact("direction")) && "방향에 '○향'을 적어 주세요",
    fact("approved") && !/\d/.test(fact("approved")) && "사용승인일은 날짜로 적어 주세요",
  ].filter(Boolean) as string[];

  const create = async () => {
    setBusy(true);
    setError(null);
    cancelled.current = false;
    let id: string | null = null;
    const stopIfCancelled = async () => {
      if (!cancelled.current) return false;
      if (id) {
        await api.cancelRun(id).catch(() => undefined);
        for (let i = 0; i < 6; i++) {
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
      const saved: Office = Object.fromEntries(
        Object.entries(office).map(([k, v]) => [k, (v ?? "").trim()]),
      ) as unknown as Office;
      setStage("사무소 정보를 저장하는 중");
      await api.saveOffice(saved).catch(() => undefined); // 저장 못 해도 영상은 만든다
      if (await stopIfCancelled()) return;
      const listing = {
        office_name: saved.office_name,
        office_address: saved.office_address,
        office_phone: saved.office_phone,
        agent_name: saved.agent_name,
        reg_no: saved.reg_no,
        prop_type: propType,
        deal,
        ...Object.fromEntries(FIELDS.map((f) => [f.key, (facts[f.key] ?? "").trim()])),
        highlights: highlights.trim(),
        nearby: nearby.trim(),
        action: saved.action,
      } as ListingBrief;
      ({ id } = await api.create({ topic: "", mode: "listing", listing }));
      if (await stopIfCancelled()) return;
      setStage(`사진 ${photos.length}장을 올리는 중`);
      uploading.current = new AbortController();
      try {
        await api.upload(
          id,
          photos.map((p) => p.file),
          true,
          photos.map((p) => p.kind ?? "living"),
          uploading.current.signal,
        );
      } catch (e) {
        if (await stopIfCancelled()) return;
        await api.deleteProject(id).catch(() => undefined);
        id = null;
        throw e;
      } finally {
        uploading.current = null;
      }
      if (await stopIfCancelled()) return;
      setStage("대사 쓰기를 시작하는 중");
      await api.runAll(id, "s1", "s6").catch(() => {});
      if (await stopIfCancelled()) return;
      router.push(`/p/${id}`);
    } catch (e) {
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
        if (ready && !blocked && !busy) create();
      }}
    >
      <Step
        n={1}
        title="중개사무소"
        done={officeDone}
        open={open.office}
        onToggle={() => toggle("office")}
        summary={
          officeDone ? `${office.office_name} · ${office.agent_name} · 바꾸기` : "한 번 넣으면 다음부터 채워져요"
        }
      >
        {offices.length > 0 && office.office_name && offices.some((o) => o.office_name === office.office_name) && (
          <button
            type="button"
            className={`self-start text-xs underline ${delArmed ? "font-semibold text-err" : "text-muted hover:text-ink"}`}
            onBlur={() => setDelArmed(false)}
            onClick={async () => {
              if (!delArmed) return setDelArmed(true);
              setDelArmed(false);
              const rows = await api.deleteOffice(office.office_name).catch(() => offices);
              setOffices(rows);
              setOffice(rows[0] ?? EMPTY_OFFICE);
            }}
          >
            {delArmed ? "지우기 (되돌릴 수 없어요)" : <>저장된 &lsquo;{office.office_name}&rsquo; 사무소 지우기</>}
          </button>
        )}
        {offices.length > 1 && (
          <select
            className={inputClass}
            aria-label="저장된 사무소"
            value={office.office_name}
            onChange={(e) => {
              const found = offices.find((o) => o.office_name === e.target.value);
              if (found) setOffice(found);
            }}
          >
            {offices.map((o) => (
              <option key={o.office_name} value={o.office_name}>
                {o.office_name}
              </option>
            ))}
          </select>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Text label="사무소 이름" max={40} value={office.office_name} hint="예: 상동 행복공인중개사사무소" onChange={(v) => setOffice({ ...office, office_name: v })} />
          <Text label="대표 공인중개사" max={20} value={office.agent_name} hint="예: 홍길동" onChange={(v) => setOffice({ ...office, agent_name: v })} />
          <Text label="사무소 소재지" max={80} value={office.office_address} hint="예: 부천시 상동 123" onChange={(v) => setOffice({ ...office, office_address: v })} />
          <Text label="연락처" max={20} value={office.office_phone} hint="예: 032-123-4567" onChange={(v) => setOffice({ ...office, office_phone: v })} />
          <Text label="등록번호" max={30} value={office.reg_no} hint="예: 41190-2020-00012" onChange={(v) => setOffice({ ...office, reg_no: v })} />
          <Text label="손님이 할 일" max={40} value={office.action} hint="예: 문자로 방문 예약해 주세요" onChange={(v) => setOffice({ ...office, action: v })} />
        </div>
        <span className="text-xs text-muted">중개보조원 정보는 광고에 넣을 수 없어 받지 않아요.</span>
      </Step>

      <Step
        n={2}
        title="매물 정보"
        done={factsDone}
        open={open.facts}
        onToggle={() => toggle("facts")}
        // 접어도 확인할 형식 문제가 있다는 것은 보이게
        summary={`필수 ${factsNeed}칸 중 ${factsFilled}칸${!open.facts && formatHints.length ? ` · 확인할 것 ${formatHints.length}개` : ""}`}
      >

      <div className="flex flex-wrap gap-4">
        <div className="flex flex-col gap-1.5">
          <span className="text-md font-semibold">매물 종류</span>
          <Seg label="매물 종류" value={propType} onChange={setPropType} options={PROPERTY} />
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-md font-semibold">거래</span>
          <Seg label="거래 형태" value={deal} onChange={setDeal} options={DEAL} />
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map((f) => (
          <Text
            key={f.key}
            label={f.label}
            max={f.max}
            value={facts[f.key] ?? ""}
            hint={f.hint}
            onChange={(v) => setFacts((o) => ({ ...o, [f.key]: v }))}
          />
        ))}
      </div>
      {/* 비워도 영상이 나온다 */}
      <Details summary="장점·주변 더 적기 (있으면)">
        <div className="flex flex-col gap-3">
          <Text label="장점 (있으면)" max={120} value={highlights} hint="직접 확인한 것만. 예: 거실 통창, 2024년 도배" onChange={setHighlights} />
          <Text label="주변 (있으면)" max={80} value={nearby} hint="거리는 도보 기준. 예: 상동역 도보 8분" onChange={setNearby} />
        </div>
      </Details>
      {formatHints.length > 0 && (
        <p className="text-sm text-stale-strong">확인해 주세요: {formatHints.join(" · ")}</p>
      )}
      <p className="text-xs text-muted">매물 정보는 적은 그대로 끝 화면과 설명란에 나가요.</p>
      </Step>

      <Step
        n={3}
        title="사진과 개인정보 확인"
        done={photos.length > 0 && photos.every((p) => p.kind) && privacy}
        open={open.photos}
        onToggle={() => toggle("photos")}
        summary={photos.length ? `${photos.length}장 · 공간 ${photos.filter((p) => p.kind).length}/${photos.length}` : "이 매물의 실제 사진만"}
      >
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" variant="ghost" onClick={() => photoInput.current?.click()} disabled={busy}>
            {photos.length ? "사진 더 넣기" : "사진 고르기"}
          </Button>
          <span className="text-sm text-muted">{photos.length ? `${photos.length}장 골랐어요` : "아직 고른 사진이 없어요"}</span>
          <input
            ref={photoInput}
            type="file"
            multiple
            accept={`.jpg,.jpeg,.png,.webp,${HEIC_ACCEPT}`}
            aria-label="매물 사진"
            className="sr-only"
            onChange={(e) => {
              addPhotos([...(e.target.files ?? [])]);
              e.target.value = "";
            }}
          />
        </div>
        {photoError && <span className="text-sm whitespace-pre-line text-err">{photoError}</span>}
        <span className="text-xs text-muted">
          이 매물의 실제 사진만 올려 주세요. 다른 집·인터넷 사진은 부당 광고예요.
        </span>
      </div>
      {photos.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-sm text-ink-2">
            사진마다 어느 공간인지 골라 주세요. 추천: 거실·방·주방·욕실
          </span>
          {photos.map((p, i) => (
            <div key={p.url} className="flex flex-wrap items-center gap-3 text-sm">
              {/* eslint-disable-next-line @next/next/no-img-element -- 고른 사진 미리보기(브라우저 안의 주소) */}
              <img src={p.url} alt="" className="h-16 w-16 flex-none rounded-ctl border border-line-strong object-cover" />
              <div className="flex min-w-0 flex-col gap-1.5">
                <span className="max-w-[260px] truncate text-muted">{p.file.name}</span>
                <Seg
                  label={`${p.file.name} 공간`}
                  value={p.kind ?? ("" as Kind)}
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
          <label className="flex items-start gap-2 text-sm text-ink-2">
            <input type="checkbox" className="mt-0.5 accent-accent" checked={privacy} onChange={(e) => setPrivacy(e.target.checked)} />
            <span>사진에 거주자 얼굴·우편물·차량 번호·가족사진 같은 개인정보가 보이지 않아요.</span>
          </label>
        </div>
      )}
      </Step>
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
                uploading.current?.abort();
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
          {busy ? "만드는 중…" : "매물 영상 만들기"}
        </Button>
        {!ready && <span className="text-sm text-muted">{needed.join(", ")} 칸을 채워 주세요.</span>}
      </div>
    </form>
  );
}

type Group = "office" | "facts" | "photos";
const OFFICE_NEED: (keyof Office)[] = ["office_name", "office_address", "office_phone", "agent_name", "reg_no"];

/** 접히는 입력 덩어리: 머리에 번호(다 채우면 ✓)와 한 줄 요약 */
function Step({
  n,
  title,
  done,
  open,
  onToggle,
  summary,
  children,
}: {
  n: number;
  title: string;
  done: boolean;
  open: boolean;
  onToggle: () => void;
  summary: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-panel bg-canvas/50 ring-1 ring-line">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-5 py-3.5 text-left"
      >
        <span
          className={`grid size-6 flex-none place-items-center rounded-full border text-xs ${done ? "border-ok/50 bg-ok-tint text-ok" : open ? "border-transparent bg-accent text-accent-ink" : "border-line-strong text-ink-2"}`}
          aria-hidden="true"
        >
          {done ? "✓" : n}
        </span>
        <span className="text-md font-semibold">{title}</span>
        <span className="ml-auto min-w-0 truncate text-right text-xs text-muted">{summary}</span>
      </button>
      {open && <div className="flex flex-col gap-3 px-5 pb-4">{children}</div>}
    </section>
  );
}

function Text({
  label,
  value,
  hint,
  onChange,
  max,
}: {
  label: string;
  value: string;
  hint: string;
  onChange: (v: string) => void;
  max: number;
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
