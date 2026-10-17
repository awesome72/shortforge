"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button, Mono, Notice, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import type { KeyCheck, KeyField, KeyStatus } from "@/lib/types";

const REQUIRED = new Set(["YOUTUBE_API_KEY", "GEMINI_API_KEY"]);

/** 화면에서 API 키를 넣고 무료 호출로 확인한 뒤 .env에 저장한다. 키 값은 서버가 다시 내보내지 않는다. */
export default function SettingsPage() {
  const [status, setStatus] = useState<KeyStatus | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [show, setShow] = useState<Record<string, boolean>>({});
  const [imageMode, setImageMode] = useState<string | null>(null);
  const [results, setResults] = useState<KeyCheck>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "info" | "warn" | "error"; text: string } | null>(null);

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
  const nothing = Object.keys(entered).length === 0 && !modeChanged;

  const run = async (save: boolean) => {
    setBusy(true);
    setMessage(null);
    try {
      if (!save) {
        const r = await api.checkKeys(entered);
        setResults(r.results);
        return;
      }
      const r = await api.saveKeys(entered, modeChanged ? (imageMode ?? undefined) : undefined);
      setResults(r.results);
      if (r.saved.length === 0) {
        setMessage({ tone: "error", text: "확인에 실패한 키가 있어 아무것도 저장하지 않았다. 아래 메시지를 보고 고친다." });
        return;
      }
      setValues({});
      setImageMode(null);
      await load();
      const left = r.setup_problems ?? [];
      setMessage(
        left.length
          ? { tone: "warn", text: `저장했다. 아직 남은 설정:\n${left.map((p) => `· ${p}`).join("\n")}` }
          : { tone: "info", text: "저장했다. 서버를 다시 시작하지 않아도 바로 쓰인다." },
      );
    } catch (e) {
      setMessage({ tone: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const fields = status?.fields ?? [];
  const mode = imageMode ?? status?.image_mode ?? "upload";
  const known = status ? mode in status.image_modes : true;

  return (
    <div className="mx-auto max-w-3xl px-6 py-14">
      <Link href="/" className="text-[13px] text-muted hover:text-ink">
        ← 홈
      </Link>
      <h1 className="mt-3 font-display text-[28px] font-bold tracking-tight">설정 · API 키</h1>
      <p className="mt-2 text-[14px] text-muted">
        키는 이 PC의 <Mono>shortforge\.env</Mono>에만 저장되고 화면에 다시 보이지 않는다. 저장하기 전에 무료 호출로
        확인한다 (YouTube 1 unit, Gemini 1토큰, Cloudflare·Pixabay는 목록·검색 1회). 결제가 연결된 Gemini 키는 저장하지
        않는다.
      </p>

      {!status && !message && <p className="mt-8 text-muted">불러오는 중…</p>}

      {status && (
        <form
          className="mt-8 flex flex-col gap-8"
          onSubmit={(e) => {
            e.preventDefault();
            if (!nothing) run(true);
          }}
        >
          <Section title="필수">
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
          </Section>

          <Section title="이미지 (선택)">
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-2 text-[13px] text-ink-2">장면 이미지를 어디서 가져올까</legend>
              {Object.entries(status.image_modes).map(([k, label]) => (
                <label key={k} className="flex items-center gap-2 text-[14px]">
                  <input type="radio" name="image_mode" checked={mode === k} onChange={() => setImageMode(k)} />
                  {label}
                  {status.image_mode === k && <span className="text-[12px] text-muted">(지금 설정)</span>}
                </label>
              ))}
              {!known && (
                <p className="text-[12px] text-muted">
                  지금 값 <Mono>{status.image_mode}</Mono>은 .env에서 직접 정한 값이다. 위에서 고르면 바뀐다.
                </p>
              )}
              <p className="text-[12px] text-muted">본인 사진을 올린 장면은 어느 방식이든 사진을 먼저 쓴다.</p>
            </fieldset>
            {fields
              .filter((f) => !REQUIRED.has(f.name))
              .filter((f) => (f.name.startsWith("CLOUDFLARE") ? mode.includes("cloudflare") : mode.includes("stock")))
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
          </Section>

          {message && <Notice tone={message.tone}>{message.text}</Notice>}

          <div className="flex flex-wrap gap-3">
            <Button type="submit" disabled={busy || nothing}>
              {busy ? "확인 중…" : "확인하고 저장"}
            </Button>
            <Button variant="ghost" disabled={busy || Object.keys(entered).length === 0} onClick={() => run(false)}>
              확인만 하기
            </Button>
          </div>
          <p className="text-[12px] text-muted">
            비워 둔 칸은 지금 값을 그대로 둔다. 다른 설정(모델, 음성, 렌더 품질)은 .env에서 바꾼다.
          </p>
        </form>
      )}
      {!status && message && (
        <div className="mt-8">
          <Notice tone={message.tone}>{message.text}</Notice>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-5 rounded-xl border border-line bg-surface p-5">
      <h2 className="font-mono text-[12px] tracking-wider text-muted">{title}</h2>
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
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="text-[14px] font-semibold">
          {field.label}
        </label>
        <span
          className={`rounded-full border px-2 py-px text-[11px] ${field.set ? "border-ok/25 bg-ok-tint text-ok" : "border-err/30 bg-err-tint text-err"}`}
        >
          {field.set ? "설정됨" : optional ? "비어 있음 (로컬 LLM이면 없어도 됨)" : "비어 있음"}
        </span>
        <a href={field.url} target="_blank" rel="noreferrer" className="ml-auto text-[12px]">
          키 받는 곳 ↗
        </a>
      </div>
      <p className="text-[12px] text-muted">{field.hint}</p>
      <div className="flex gap-2">
        <input
          id={id}
          className={`${inputClass} min-w-0 flex-1 font-mono`}
          type={shown ? "text" : "password"}
          autoComplete="off"
          spellCheck={false}
          placeholder={field.set ? "바꿀 때만 새 값을 붙여 넣는다" : "여기에 붙여 넣는다"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <Button variant="ghost" onClick={onToggle} disabled={!value} aria-label={shown ? "가리기" : "보기"}>
          {shown ? "가리기" : "보기"}
        </Button>
      </div>
      {result && (
        <p
          className={`text-[13px] ${result.ok === true ? "text-ok" : result.ok === false ? "text-err" : "text-stale-strong"}`}
        >
          {result.ok === true ? "✓ " : result.ok === false ? "✕ " : "! "}
          {result.message}
        </p>
      )}
    </div>
  );
}
