"use client";

import Link from "next/link";
import { AppBar } from "@/components/AppBar";
import { useEffect, useState } from "react";
import { Chips, ConfirmInline } from "@/components/Confirm";
import { THEME_LABEL, applyTheme, useTheme, type Theme } from "@/components/ThemeToggle";
import { Button, Details, Mono, Notice, Seg, inputClass, switchClass } from "@/components/ui";
import { api } from "@/lib/api";
import type {
  AdvancedProvider,
  AdvancedStatus,
  KeyCheck,
  KeyField,
  KeyStatus,
  VideoGenStatus,
} from "@/lib/types";

const REQUIRED = new Set(["YOUTUBE_API_KEY", "GEMINI_API_KEY"]);

/** 화면에서 API 키를 넣고 무료 호출로 확인한 뒤 .env에 저장한다. 키 값은 서버가 다시 내보내지 않는다. */
export default function SettingsPage() {
  const [status, setStatus] = useState<KeyStatus | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [show, setShow] = useState<Record<string, boolean>>({});
  const [imageMode, setImageMode] = useState<string | null>(null);
  const [advProvider, setAdvProvider] = useState<AdvancedProvider | null>(null);
  const [results, setResults] = useState<KeyCheck>({});
  const [busy, setBusy] = useState(false);
  // where: 메시지를 띄울 묶음 (저장 버튼이 묶음마다 있어 누른 자리 가까이에 보인다)
  const [message, setMessage] = useState<{ tone: "info" | "warn" | "error"; text: string; where?: string } | null>(
    null,
  );

  const load = () =>
    api
      .keys()
      .then(setStatus)
      .catch((e) => setMessage({ tone: "error", text: (e as Error).message }));
  useEffect(() => {
    load();
  }, []);

  const entered = Object.fromEntries(
    Object.entries(values)
      .map(([k, v]) => [k, v.trim()])
      .filter(([, v]) => v),
  );
  const modeChanged = imageMode !== null && imageMode !== status?.image_mode;
  // 묶음 하나의 키만 확인·저장한다 (맨 아래 버튼 하나가 다른 묶음까지 저장하는 것처럼 보였다)
  const enteredIn = (names: string[]): Record<string, string> =>
    Object.fromEntries(Object.entries(entered).filter(([k]) => names.includes(k))) as Record<string, string>;

  const run = async (save: boolean, names: string[], where: string, withMode = false) => {
    const keys = enteredIn(names);
    setBusy(true);
    setMessage(null);
    try {
      if (!save) {
        const r = await api.checkKeys(keys);
        setResults(r.results);
        return;
      }
      const r = await api.saveKeys(keys, withMode && modeChanged ? (imageMode ?? undefined) : undefined);
      setResults(r.results);
      if (r.saved.length === 0 && Object.keys(keys).length > 0) {
        setMessage({ tone: "error", where, text: "확인에 실패한 키가 있어 저장하지 않았어요. 칸 아래 메시지를 보고 고쳐 주세요." });
        return;
      }
      setValues((v) => Object.fromEntries(Object.entries(v).filter(([k]) => !names.includes(k))));
      if (withMode) setImageMode(null);
      await load();
      const left = r.setup_problems ?? [];
      setMessage(
        left.length
          ? { tone: "warn", where, text: `저장했어요. 아직 남은 설정:\n${left.map((p) => `· ${p}`).join("\n")}` }
          : { tone: "info", where, text: "저장했어요. 바로 쓰여요." },
      );
    } catch (e) {
      setMessage({ tone: "error", where, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const show_ = (where: string) => (message && (message.where ?? "") === where ? message : null);
  const saveBar = (names: string[], where: string, withMode = false) => {
    const n = Object.keys(enteredIn(names)).length;
    return (
      <div className="flex flex-col gap-2">
        {show_(where) && <Notice tone={show_(where)!.tone}>{show_(where)!.text}</Notice>}
        <div className="flex flex-wrap gap-3">
          <Button disabled={busy || (n === 0 && !(withMode && modeChanged))} onClick={() => run(true, names, where, withMode)}>
            {busy ? "확인 중…" : withMode && n === 0 ? "저장" : "키 확인하고 저장"}
          </Button>
          <Button variant="ghost" disabled={busy || n === 0} onClick={() => run(false, names, where)}>
            확인만 하기
          </Button>
        </div>
      </div>
    );
  };

  const fields = status?.fields ?? [];
  const names = (pick: (f: KeyField) => boolean) => fields.filter(pick).map((f) => f.name);
  const requiredOk = fields.filter((f) => REQUIRED.has(f.name)).every((f) => f.set || (f.name === "GEMINI_API_KEY" && status?.llm_mode === "ollama"));
  const paidOn = !!status && (status.advanced.mode !== "off" || status.video_gen.mode === "hf");
  const provider = advProvider ?? status?.advanced.provider ?? "anthropic";
  const providerKey = `${provider.toUpperCase()}_API_KEY`;
  const mode = imageMode ?? status?.image_mode ?? "auto";
  const known = status ? mode in status.image_modes : true;

  return (
    <>
    <AppBar
      crumb="설정 · API 키"
      right={
        <Link
          href="/"
          className="inline-flex min-h-9 items-center rounded-ctl px-3.5 text-sm font-semibold text-ink-2 no-underline hover:bg-card hover:text-ink"
        >
          ← 스튜디오로
        </Link>
      }
    />
    <div className="sf-enter mx-auto max-w-5xl px-4 pt-12 pb-16 sm:px-6">
      <span className="rounded bg-accent-tint px-[7px] py-0.5 font-mono text-xs text-accent">SETTINGS</span>
      <h1 className="mt-3 text-2xl leading-[1.2] font-bold tracking-[-0.035em]">설정</h1>
      <p className="mt-2 text-md text-ink-2">
        키는 이 PC에만 저장돼요. 저장 전에 무료로 확인해요.
      </p>

      {!status && !message && <p className="mt-8 text-muted">불러오는 중…</p>}

      {status && (
        <div className="mt-8 grid gap-8 lg:grid-cols-[190px_minmax(0,1fr)]">
        <nav aria-label="설정 묶음" className="hidden flex-col gap-0.5 self-start text-sm lg:sticky lg:top-20 lg:flex">
          {[
            { id: "keys", label: "꼭 필요한 키", dot: requiredOk ? "bg-ok" : "bg-stale" },
            { id: "image", label: "그림", dot: "bg-ok" },
            { id: "features", label: "쓸 기능", dot: "bg-muted" },
            { id: "paid", label: "돈이 들 수 있는 기능", dot: paidOn ? "bg-stale" : "bg-ok" },
          ].map((t) => (
            <a
              key={t.id}
              href={`#${t.id}`}
              className="flex items-center gap-2.5 rounded-ctl px-3 py-2 text-ink-2 no-underline hover:bg-surface hover:text-ink"
            >
              <span className={`size-2 flex-none rounded-full ${t.dot}`} aria-hidden="true" />
              {t.label}
            </a>
          ))}
        </nav>
        <form
          className="flex min-w-0 flex-col gap-8"
          onSubmit={(e) => {
            e.preventDefault();
            // Enter: 커서가 있는 키 칸이 속한 묶음만 확인·저장한다 (예전처럼 붙여 넣고 Enter)
            const name = (document.activeElement as HTMLElement | null)?.id?.replace(/^key-/, "") ?? "";
            const f = fields.find((x) => x.name === name);
            if (!f || busy || !entered[name]) return;
            if (REQUIRED.has(f.name)) run(true, names((x) => REQUIRED.has(x.name)), "required");
            else if (f.group === "basic") run(true, names((x) => x.group === "basic" && !REQUIRED.has(x.name)), "image", true);
            else if (f.group === "video") run(true, names((x) => x.group === "video"), "video-key");
            else run(true, [f.name], "advanced-key");
          }}
        >
          {show_("") && <Notice tone={show_("")!.tone}>{show_("")!.text}</Notice>}
          <Section id="keys" title="1. 꼭 필요한 키" badge={requiredOk ? { ok: true, text: "준비됨" } : { ok: false, text: "키가 필요해요" }}>
            {fields
              .filter((f) => REQUIRED.has(f.name))
              .map((f) => (
                <KeyInput
                  key={f.name}
                  field={f}
                  optional={f.name === "GEMINI_API_KEY" && status.llm_mode === "ollama"}
                  value={values[f.name] ?? ""}
                  shown={!!show[f.name]}
                  result={results[f.name]}
                  onChange={(v) => setValues((o) => ({ ...o, [f.name]: v }))}
                  onToggle={() => setShow((o) => ({ ...o, [f.name]: !o[f.name] }))}
                />
              ))}
            {saveBar(names((f) => REQUIRED.has(f.name)), "required")}
          </Section>

          <Section
            id="image"
            title="2. 그림"
            badge={{ ok: true, text: status.image_modes[status.image_mode]?.split(" (")[0] ?? status.image_mode }}
          >
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-2 text-sm text-ink-2">장면 그림을 어디서 가져올지 골라 주세요</legend>
              {Object.entries(status.image_modes).map(([k, label]) => (
                <label key={k} className="flex items-center gap-2 text-md">
                  <input type="radio" name="image_mode" checked={mode === k} onChange={() => setImageMode(k)} />
                  {label}
                  {status.image_mode === k && <span className="text-xs text-muted">(지금 설정)</span>}
                </label>
              ))}
              {!known && (
                <p className="text-xs text-muted">
                  지금은 설정 파일에 직접 적은 방식(<Mono>{status.image_mode}</Mono>)을 쓰고 있어요. 위에서 고르면 바뀌어요.
                </p>
              )}
              <p className="text-xs text-muted">본인 사진을 올린 장면은 어느 방식이든 사진을 먼저 써요.</p>
            </fieldset>
            {fields
              .filter((f) => f.group === "basic" && !REQUIRED.has(f.name))
              .filter(
                (f) =>
                  mode === "auto" || // 자동은 키가 있는 소스를 모두 쓴다. 이 칸이 안 보여 첫 사용자가 키를 못 넣었다
                  (f.name.startsWith("CLOUDFLARE") ? mode.includes("cloudflare") : mode.includes("stock")),
              )
              .map((f) => (
                <KeyInput
                  key={f.name}
                  field={f}
                  optional={false}
                  value={values[f.name] ?? ""}
                  shown={!!show[f.name]}
                  result={results[f.name]}
                  onChange={(v) => setValues((o) => ({ ...o, [f.name]: v }))}
                  onToggle={() => setShow((o) => ({ ...o, [f.name]: !o[f.name] }))}
                />
              ))}
            {saveBar(names((f) => f.group === "basic" && !REQUIRED.has(f.name)), "image", true)}
          </Section>

          <Section id="features" title="3. 쓸 기능" note="켜면 바로 저장돼요">
            <ThemeChoice />
            <BusinessControls
              onSaved={(text) => setMessage({ tone: "info", text, where: "features" })}
              onError={(text) => setMessage({ tone: "error", text, where: "features" })}
            />
            <ListingControls
              onSaved={(text) => setMessage({ tone: "info", text, where: "features" })}
              onError={(text) => setMessage({ tone: "error", text, where: "features" })}
            />
            <PrerenderControls
              onSaved={(text) => setMessage({ tone: "info", text, where: "features" })}
              onError={(text) => setMessage({ tone: "error", text, where: "features" })}
            />
            <BrandControls
              onSaved={(text) => setMessage({ tone: "info", text, where: "features" })}
              onError={(text) => setMessage({ tone: "error", text, where: "features" })}
            />
            {show_("features") && <Notice tone={show_("features")!.tone}>{show_("features")!.text}</Notice>}
          </Section>

          <Section
            id="paid"
            title="4. 돈이 들 수 있는 기능"
            badge={paidOn ? { ok: false, text: "유료 기능 켜짐" } : { ok: true, text: "유료 기능 꺼짐 · ₩0" }}
            accent
          >
            <h3 className="text-md font-semibold">고급 모드</h3>
            <p className="-mt-3 text-sm text-ink-2">
              분석과 대사만 유료 AI가 써요. 하루 예산을 넘거나 실패하면 무료로 처리해요. 끄면 ₩0이에요.
            </p>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-ink-2">어느 서비스의 키를 쓸까</span>
              <select
                className={inputClass}
                value={provider}
                onChange={(e) => setAdvProvider(e.target.value as AdvancedProvider)}
              >
                {Object.entries(status.advanced.providers).map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                    {id === "openrouter" ? " (키 하나로 Claude·GPT 등 여러 모델)" : ""}
                    {status.advanced.mode === id ? " — 지금 사용 중" : ""}
                  </option>
                ))}
              </select>
            </label>
            {fields
              .filter((f) => f.name === providerKey)
              .map((f) => (
                <KeyInput
                  key={f.name}
                  field={f}
                  optional
                  value={values[f.name] ?? ""}
                  shown={!!show[f.name]}
                  result={results[f.name]}
                  onChange={(v) => setValues((o) => ({ ...o, [f.name]: v }))}
                  onToggle={() => setShow((o) => ({ ...o, [f.name]: !o[f.name] }))}
                />
              ))}
            {fields.some((f) => f.name === providerKey) && saveBar([providerKey], "advanced-key")}
            <AdvancedControls
              key={provider}
              provider={provider}
              status={status.advanced}
              keySet={fields.some((f) => f.name === providerKey && f.set)}
              onSaved={async (text) => {
                await load();
                setMessage({ tone: "info", text, where: "advanced" });
              }}
              onError={(text) => setMessage({ tone: "error", text, where: "advanced" })}
            />
            {show_("advanced") && <Notice tone={show_("advanced")!.tone}>{show_("advanced")!.text}</Notice>}

            <h3 className="border-t border-line pt-5 text-md font-semibold">AI로 움직이기</h3>
            <p className="-mt-3 text-sm text-ink-2">
              장면 그림을 움직이는 영상으로 바꿔요. 다듬기 화면에서 직접 누른 장면만 만들어요.
            </p>
            {fields
              .filter((f) => f.group === "video")
              .map((f) => (
                <KeyInput
                  key={f.name}
                  field={f}
                  optional
                  value={values[f.name] ?? ""}
                  shown={!!show[f.name]}
                  result={results[f.name]}
                  onChange={(v) => setValues((o) => ({ ...o, [f.name]: v }))}
                  onToggle={() => setShow((o) => ({ ...o, [f.name]: !o[f.name] }))}
                />
              ))}
            {fields.some((f) => f.group === "video") && saveBar(names((f) => f.group === "video"), "video-key")}
            <VideoGenControls
              status={status.video_gen}
              keySet={fields.some((f) => f.group === "video" && f.set)}
              onSaved={async (text) => {
                await load();
                setMessage({ tone: "info", text, where: "video" });
              }}
              onError={(text) => setMessage({ tone: "error", text, where: "video" })}
            />
            {show_("video") && <Notice tone={show_("video")!.tone}>{show_("video")!.text}</Notice>}
          </Section>

          {/* 개발자용 정보는 한곳에 */}
          <Details summary="고급 정보" className="text-xs text-muted">
            <p>
              키는 <Mono>shortforge\.env</Mono>에 저장되고 화면에 다시 보이지 않아요. 비운 칸은 그대로 둬요. 확인은 YouTube
              1 unit, Gemini 1토큰, Cloudflare·Pixabay는 목록·검색 1회, Anthropic·OpenAI는 모델 목록 조회로 해요. 결제가
              연결된 Gemini 키는 유료 등급이라 저장하지 않아요. 그 밖의 설정(AI 모델, 목소리, 영상 품질)은 설정 파일에서
              바꿔요.
            </p>
          </Details>
        </form>
        </div>
      )}
      {!status && message && (
        <div className="mt-8">
          <Notice tone={message.tone}>{message.text}</Notice>
        </div>
      )}
    </div>
    </>
  );
}

/** 화면 밝기 (이 브라우저에만 기억한다) */
function ThemeChoice() {
  const theme = useTheme();
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <span className="min-w-[160px] flex-1">
        <span className="block font-medium text-ink-2">화면 밝기</span>
        <span className="block text-muted">밝은 사무실에서는 &apos;밝게&apos;가 잘 보여요.</span>
      </span>
      <div className="w-full max-w-[300px]">
        <Seg
          label="화면 밝기"
          value={theme}
          onChange={(v: Theme) => applyTheme(v)}
          options={(["dark", "light", "system"] as const).map((v) => ({ value: v, label: THEME_LABEL[v] }))}
        />
      </div>
    </div>
  );
}

/** 다듬는 동안 장면 영상을 미리 만들기. 완성 대기가 줄지만 그동안 CPU를 쓴다 */
function BusinessControls({ onSaved, onError }: { onSaved: (t: string) => void; onError: (t: string) => void }) {
  const [on, setOn] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api
      .config()
      .then((c) => setOn(!!c.business_mode))
      .catch(() => setOn(false));
  }, []);
  const toggle = async (next: boolean) => {
    setBusy(true);
    try {
      const r = await api.saveBusiness(next);
      setOn(r.business_mode);
      onSaved(r.business_mode ? "첫 화면에 '우리 가게 홍보'가 나타나요." : "'우리 가게 홍보'를 숨겼어요.");
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <label className="flex items-start gap-2.5 text-sm text-ink-2">
      <input
        type="checkbox"
        role="switch"
        className={switchClass}
        checked={!!on}
        disabled={busy || on === null}
        onChange={(e) => toggle(e.target.checked)}
      />
      <span>
        <span className="font-medium">우리 가게 홍보 영상 (시험 기능)</span>
        <span className="block text-muted">
          첫 화면에 가게 홍보 입력이 나와요. 수익 목적이면 AI 서비스의 상업 이용 조건을 확인해 주세요.
        </span>
      </span>
    </label>
  );
}

/** 부동산 매물 홍보 (시험 기능) */
function ListingControls({ onSaved, onError }: { onSaved: (t: string) => void; onError: (t: string) => void }) {
  const [on, setOn] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api
      .config()
      .then((c) => setOn(!!c.listing_mode))
      .catch(() => setOn(false));
  }, []);
  const toggle = async (next: boolean) => {
    setBusy(true);
    try {
      const r = await api.saveListing(next);
      setOn(r.listing_mode);
      onSaved(r.listing_mode ? "첫 화면에 '부동산 매물 홍보'가 나타나요." : "'부동산 매물 홍보'를 숨겼어요.");
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <label className="flex items-start gap-2.5 text-sm text-ink-2">
      <input
        type="checkbox"
        role="switch"
        className={switchClass}
        checked={!!on}
        disabled={busy || on === null}
        onChange={(e) => toggle(e.target.checked)}
      />
      <span>
        <span className="font-medium">부동산 매물 홍보 영상 (시험 기능)</span>
        <span className="block text-muted">
          첫 화면에 매물 소개 입력이 나와요. 광고에 밝혀야 하는 정보를 영상 끝과 설명란에 넣어요.
        </span>
      </span>
    </label>
  );
}

function PrerenderControls({ onSaved, onError }: { onSaved: (t: string) => void; onError: (t: string) => void }) {
  const [on, setOn] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api
      .config()
      .then((c) => setOn(!!c.prerender_clips))
      .catch(() => setOn(false));
  }, []);
  const toggle = async (next: boolean) => {
    setBusy(true);
    try {
      const r = await api.savePrerender(next);
      setOn(r.prerender_clips);
      onSaved(r.prerender_clips ? "다듬는 동안 영상을 미리 준비해요." : "미리 준비를 껐어요.");
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <label className="flex items-start gap-2.5 text-sm text-ink-2">
      <input
        type="checkbox"
        role="switch"
        className={switchClass}
        checked={!!on}
        disabled={busy || on === null}
        onChange={(e) => toggle(e.target.checked)}
      />
      <span>
        <span className="font-medium">다듬는 동안 영상을 미리 준비하기</span>
        <span className="block text-muted">
          &apos;영상 완성하기&apos;가 2~3배 빨라져요. 느린 PC에서는 꺼 두세요.
        </span>
      </span>
    </label>
  );
}

/** 엔딩 카드의 채널 이름. 키와 따로 바로 저장한다 (다시 렌더하면 반영) */
function BrandControls({ onSaved, onError }: { onSaved: (t: string) => void; onError: (t: string) => void }) {
  const [saved, setSaved] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api
      .config()
      .then((c) => {
        setSaved(c.brand_name ?? "");
        setName(c.brand_name ?? "");
      })
      .catch(() => setSaved(""));
  }, []);
  const save = async () => {
    setBusy(true);
    try {
      const r = await api.saveBrand(name);
      setSaved(r.brand_name);
      setName(r.brand_name);
      onSaved(
        r.brand_name
          ? `끝 화면에 ${r.brand_name.startsWith("@") ? r.brand_name : "@" + r.brand_name}을 넣어요. 다시 완성하면 들어가요.`
          : "끝 화면을 껐어요.",
      );
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-2 text-sm">
      <label className="flex flex-col gap-1">
        <span className="font-medium text-ink-2">끝 화면 채널 이름</span>
        <span className="text-muted">영상 마지막 2.4초에 보여요. 비우면 끝 화면 없이 끝나요.</span>
        <div className="flex flex-wrap gap-2">
          <input
            className={`${inputClass} min-w-0 flex-1`}
            value={name}
            maxLength={30}
            placeholder="예: @mychannel"
            onChange={(e) => setName(e.target.value)}
          />
          <Button variant="ghost" disabled={busy || saved === null || name.trim() === saved} onClick={save}>
            {busy ? "저장 중…" : "저장"}
          </Button>
        </div>
      </label>
    </div>
  );
}

function Section({
  id,
  title,
  badge,
  note,
  accent = false,
  children,
}: {
  id: string; // 왼쪽 목차가 가리키는 자리
  title: string;
  badge?: { ok: boolean; text: string }; // 묶음의 지금 상태를 한 단어로
  note?: string;
  accent?: boolean; // 돈이 들 수 있는 묶음
  children: React.ReactNode;
}) {
  return (
    <section
      id={id}
      className={`flex scroll-mt-24 flex-col gap-5 rounded-panel bg-surface p-[22px] ${accent ? "shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-accent)_40%,transparent),var(--shadow-panel)]" : "shadow-panel"}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        {badge && (
          <span
            className={`rounded-full border px-2 py-px text-2xs ${badge.ok ? "border-ok/25 bg-ok-tint text-ok" : "border-stale-line bg-stale-tint text-stale"}`}
          >
            {badge.text}
          </span>
        )}
        {note && <span className="ml-auto text-xs text-muted">{note}</span>}
      </div>
      {children}
    </section>
  );
}

function KeyInput({
  field,
  optional,
  value,
  shown,
  result,
  onChange,
  onToggle,
}: {
  field: KeyField;
  optional: boolean;
  value: string;
  shown: boolean;
  result?: { ok: boolean | null; message: string };
  onChange: (v: string) => void;
  onToggle: () => void;
}) {
  const id = `key-${field.name}`;
  const [editing, setEditing] = useState(false);
  // 이미 설정된 키는 한 줄로 접는다 (할 일이 없는 입력칸이 설정 화면의 절반이었다)
  if (field.set && !editing && !value && !result) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-ctl bg-card px-3.5 py-2.5">
        <span className="min-w-[160px] flex-1">
          <span className="block text-md font-semibold">{field.label}</span>
          <span className="block text-xs text-muted">{field.hint}</span>
        </span>
        <span className="rounded-full bg-ok-tint px-2 py-px text-2xs text-ok">✓ 설정됨</span>
        <Button variant="quiet" aria-label={`${field.label} 바꾸기`} onClick={() => setEditing(true)}>
          바꾸기
        </Button>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="text-md font-semibold">
          {field.label}
        </label>
        <span
          className={`rounded-full border px-2 py-px text-2xs ${field.set ? "border-ok/25 bg-ok-tint text-ok" : "border-err/30 bg-err-tint text-err"}`}
        >
          {field.set
            ? "설정됨"
            : field.group === "advanced"
              ? "비어 있음 (고급 모드를 쓸 때만)"
              : field.group === "video"
                ? "비어 있음 (유료 방식을 쓸 때만)"
                : optional
                ? "비어 있음 (이 PC의 AI 프로그램을 쓰면 없어도 돼요)"
                : "비어 있음"}
        </span>
        <a href={field.url} target="_blank" rel="noreferrer" className="ml-auto text-xs">
          키 받는 곳 ↗
        </a>
      </div>
      <p className="text-xs text-muted">{field.hint}</p>
      <div className="flex gap-2">
        <input
          id={id}
          className={`${inputClass} min-w-0 flex-1 font-mono placeholder:font-sans`}
          type={shown ? "text" : "password"}
          autoComplete="off"
          spellCheck={false}
          placeholder={field.set ? "새 값을 붙여 넣고 Enter" : "여기에 붙여 넣고 Enter"}
          autoFocus={editing}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <Button variant="ghost" onClick={onToggle} disabled={!value} aria-label={shown ? "가리기" : "보기"}>
          {shown ? "가리기" : "보기"}
        </Button>
      </div>
      {result && (
        <p
          className={`text-sm ${result.ok === true ? "text-ok" : result.ok === false ? "text-err" : "text-stale-strong"}`}
        >
          {result.ok === true ? "✓ " : result.ok === false ? "✕ " : "! "}
          {result.message}
        </p>
      )}
    </div>
  );
}

function VideoGenControls({
  status,
  keySet,
  onSaved,
  onError,
}: {
  status: VideoGenStatus;
  keySet: boolean;
  onSaved: (text: string) => Promise<void>;
  onError: (text: string) => void;
}) {
  const [budget, setBudget] = useState(String(status.budget_usd));
  const [asking, setAsking] = useState(false); // 켜기 전 확인 (동의 문구를 그 안에)
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"space" | "hf">(status.mode === "hf" ? "hf" : "space");
  const on = status.mode !== "off";
  const paid = mode === "hf";
  const budgetNum = Number(budget);
  const budgetOk = !paid || (Number.isFinite(budgetNum) && budgetNum >= 0.1 && budgetNum <= 100);
  const perScene = status.usd_per_sec * 5.5; // 장면 대부분이 5초 안팎이고 전환 몫을 더 만든다

  const save = async (next: boolean) => {
    setBusy(true);
    try {
      await api.saveVideoGen(
        next ? { on: true, mode, accept_cost: true, ...(paid ? { daily_budget_usd: budgetNum } : {}) } : { on: false },
      );
      await onSaved(
        !next
          ? "AI로 움직이기를 껐어요."
          : paid
            ? `AI로 움직이기를 켰어요. 하루 $${budgetNum.toFixed(2)}까지만 써요.`
            : "AI로 움직이기를 켰어요. 다듬기 화면의 장면에서 'AI로 움직이기'를 눌러 보세요.",
      );
      setAsking(false);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span
          className={`rounded-full border px-2 py-px text-2xs ${on ? "border-accent/30 bg-accent-tint text-accent" : "border-line-strong text-muted"}`}
        >
          {on ? "켜짐" : "꺼짐"}
        </span>
        {paid && (
          <span className="text-muted tabular-nums">
            오늘 사용 ${status.spend.used_usd.toFixed(2)} / ${status.spend.budget_usd.toFixed(2)} (매일 오전 9시에 다시 시작)
          </span>
        )}
      </div>
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-ink-2">어떤 방식으로 만들까</span>
        <select
          className={inputClass}
          value={mode}
          onChange={(e) => {
            setMode(e.target.value as "space" | "hf");
            setAsking(false); // 방식마다 동의 내용이 다르다
          }}
        >
          <option value="space">무료 데모 서버</option>
          <option value="hf">유료 서비스 (내 Hugging Face 크레딧)</option>
        </select>
      </label>
      {paid && (
        <label className="flex max-w-[220px] flex-col gap-1 text-sm">
          <span className="font-medium text-ink-2">하루 예산 (USD)</span>
          <input className={inputClass} inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} />
        </label>
      )}
      <Chips
        items={
          paid
            ? [{ text: `장면당 약 $${perScene.toFixed(2)}`, tone: "money" }, "장면당 몇 분", "하루 예산 안에서만"]
            : ["무료", "장면당 30초쯤", "최대 7초", { text: "그림이 외부 데모 서버로 가요", tone: "out" }]
        }
      />
      <Details className="text-xs text-muted">
        {paid ? (
          <p>
            {status.label} · 1초에 약 ${status.usd_per_sec.toFixed(3)}. 실제 청구는 Hugging Face 계정에서 하고, 이 화면의
            사용액은 공개 가격으로 계산한 어림값이에요. 무료 계정에는 크레딧이 없어 먼저 충전해야 해요. 요청이 접수되면
            사용액에 먼저 넣고 실패하면 되돌려요. 하루 예산을 넘으면 멈춰요.
          </p>
        ) : (
          <p>
            하루 사용량 제한이 있고, 데모 서버라 붐비거나 멈출 수 있어요. 7초보다 긴 장면은 마지막 화면이 멈춰 있어요.
            낮은 해상도로 만들어 키우기 때문에 조금 부드러워 보여요. 모델 조건에 따라 AI로 만들었다고 밝혀야 하고, 다른
            사람 흉내, 괴롭힘, 의료 조언 등에는 쓸 수 없어요.
          </p>
        )}
      </Details>
      {paid && !keySet && <p className="text-xs text-stale-strong">먼저 위에 토큰을 넣고 &quot;키 확인하고 저장&quot;을 눌러 주세요.</p>}
      <div className="flex flex-wrap gap-3">
        <Button disabled={busy || asking || (paid && !keySet) || !budgetOk} onClick={() => setAsking(true)}>
          {on ? "설정 저장" : "AI로 움직이기 켜기"}
        </Button>
        {on && (
          <Button variant="ghost" disabled={busy} onClick={() => save(false)}>
            끄기
          </Button>
        )}
      </div>
      {asking && (
        <ConfirmInline
          kind={paid ? "money" : "out"}
          question={
            paid
              ? "영상을 만들 때마다 Hugging Face 크레딧이 쓰인다는 것을 이해했어요."
              : "누른 장면의 그림과 영어 장면 설명이 공개 데모 서버(외부)로 올라간다는 것을 이해했어요. 토큰을 넣었다면 토큰도 함께 보내져요."
          }
          chips={paid ? [{ text: `하루 최대 $${budgetOk ? budgetNum.toFixed(2) : "?"}`, tone: "money" }] : []}
          confirmLabel={on ? "동의하고 저장" : "동의하고 켜기"}
          disabled={busy || !budgetOk}
          onConfirm={() => save(true)}
          onCancel={() => setAsking(false)}
        />
      )}
    </div>
  );
}

const EFFORT_LABEL = { low: "빠르게", medium: "보통", high: "깊게 (느리고 비싸요)" } as const;

/** 고급 모드 켜기·끄기. 켤 때는 과금 동의가 필요하다. */
function AdvancedControls({
  provider,
  status,
  keySet,
  onSaved,
  onError,
}: {
  provider: AdvancedProvider;
  status: AdvancedStatus;
  keySet: boolean;
  onSaved: (text: string) => Promise<void>;
  onError: (text: string) => void;
}) {
  const models = status.models[provider] ?? {};
  const name = status.providers[provider];
  // 다른 서비스를 고르면 그 서비스의 추천 모델(D13 실측)부터 보여 준다
  const [model, setModel] = useState(
    provider === status.provider ? status.model : (status.defaults[provider] ?? Object.keys(models)[0] ?? ""),
  );
  const [effort, setEffort] = useState(status.effort);
  const [budget, setBudget] = useState(String(status.budget_usd));
  const [asking, setAsking] = useState(false); // 켜기 전 확인 (과금 동의를 그 안에)
  const [busy, setBusy] = useState(false);
  const on = status.mode === provider;
  const otherOn = status.mode !== "off" && !on;
  const price = models[model];
  const budgetNum = Number(budget);
  const budgetOk = Number.isFinite(budgetNum) && budgetNum >= 0.1 && budgetNum <= 100;

  const save = async (mode: "off" | AdvancedProvider) => {
    setBusy(true);
    try {
      const r = await api.saveAdvanced(
        mode === "off" ? { mode } : { mode, model, effort, daily_budget_usd: budgetNum, accept_cost: true },
      );
      const left = r.setup_problems.filter((p) => p.includes("고급 모드"));
      await onSaved(
        mode === "off"
          ? "고급 모드를 껐어요. 다시 비용 없이 무료 경로만 써요."
          : left.length
            ? `저장했지만 아직 쓸 수 없어요:\n${left.join("\n")}`
            : `고급 모드를 켰어요 (${models[model]?.label ?? model}). 하루 $${budgetNum.toFixed(2)}까지 써요.`,
      );
      setAsking(false);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span
          className={`rounded-full border px-2 py-px text-2xs ${on ? "border-accent/30 bg-accent-tint text-accent-strong" : "border-line bg-canvas text-muted"}`}
        >
          {on ? "켜짐" : otherOn ? `꺼짐 (지금은 ${status.providers[status.mode as AdvancedProvider]} 사용 중)` : "꺼짐"}
        </span>
        <span className="text-muted">
          오늘 사용 ${status.spend.used_usd.toFixed(4)} / ${status.spend.budget_usd.toFixed(2)}
        </span>
      </div>
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-ink-2">모델</span>
        <select className={inputClass} value={model} onChange={(e) => setModel(e.target.value)}>
          {Object.entries(models).map(([id, m]) => (
            <option key={id} value={id}>
              {m.label} — 입력 ${m.input} / 출력 ${m.output} (100만 토큰당)
            </option>
          ))}
        </select>
      </label>
      <div className="flex flex-wrap gap-3">
        <label className="flex min-w-[180px] flex-1 flex-col gap-1 text-sm">
          <span className="font-medium text-ink-2">생각 깊이</span>
          <select
            className={inputClass}
            value={effort}
            onChange={(e) => setEffort(e.target.value as AdvancedStatus["effort"])}
          >
            {Object.entries(EFFORT_LABEL).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-[140px] flex-1 flex-col gap-1 text-sm">
          <span className="font-medium text-ink-2">하루 예산 (USD)</span>
          <input
            className={inputClass}
            inputMode="decimal"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
          />
        </label>
      </div>
      {price && (
        <Details summary="비용 어림" className="text-xs text-muted">
          <p>
          영상 1편에 유료 호출은 보통 2~4회예요(실측: Claude Opus 5.5 약 $0.16, GPT-5.6 Sol 약 $0.12, Sonnet 5.5·Terra 약
          $0.06~0.08, Haiku 5.5·Luna 1센트 미만). 실제 비용은 {name} 계정에서 청구되며, 이 화면의 사용액은 응답의 토큰 수로 계산한 추정치예요
          {provider === "openrouter" ? "(OpenRouter는 응답에 실제 청구액이 오면 그 값을 써요)" : ""}.
          </p>
        </Details>
      )}
      {!keySet && <p className="text-xs text-stale-strong">먼저 위에 {name} API 키를 넣고 &quot;키 확인하고 저장&quot;을 눌러 주세요.</p>}
      <div className="flex flex-wrap gap-3">
        <Button disabled={busy || asking || !keySet || !budgetOk} onClick={() => setAsking(true)}>
          {on ? "고급 모드 설정 저장" : otherOn ? `${name}로 바꿔 켜기` : "고급 모드 켜기"}
        </Button>
        {status.mode !== "off" && (
          <Button variant="ghost" disabled={busy} onClick={() => save("off")}>
            고급 모드 끄기
          </Button>
        )}
      </div>
      {asking && (
        <ConfirmInline
          kind="money"
          question={`고급 모드를 쓰면 ${name} 계정에 비용이 청구될 수 있다는 것을 이해했어요.`}
          chips={[{ text: `하루 최대 $${budgetOk ? budgetNum.toFixed(2) : "?"}`, tone: "money" }, "분석·대사만 유료"]}
          confirmLabel={on ? "동의하고 저장" : "동의하고 켜기"}
          disabled={busy || !budgetOk}
          onConfirm={() => save(provider)}
          onCancel={() => setAsking(false)}
        />
      )}
    </div>
  );
}
