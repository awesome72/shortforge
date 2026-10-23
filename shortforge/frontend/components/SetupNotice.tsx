import Link from "next/link";
import type { AppConfig } from "@/lib/types";

/** .env에 빠진 키가 있으면 무엇을 채울지 알려 준다. 서버는 떠 있고, 그 키가 필요한 단계만 실패한다. */
export function SetupNotice({ config, className = "" }: { config: AppConfig | null; className?: string }) {
  const problems = config?.setup_problems ?? [];
  const unused = config && config.image_sources.length === 0 ? (config.image_unused ?? []) : [];
  if (problems.length === 0) {
    if (unused.length === 0) return null;
    return (
      <div className={`border-b border-stale-line bg-stale-tint px-7 py-2 text-[12px] text-stale-strong ${className}`}>
        이미지 방식이 &quot;본인 사진만&quot;인데 {unused.join("·")} 키가 있어요. 사진 없이 만들려면{" "}
        <Link href="/settings" className="font-semibold text-stale-strong underline">
          설정에서 이미지 방식 바꾸기
        </Link>
      </div>
    );
  }
  return (
    <div className={`border-b border-err/30 bg-err-tint px-7 py-2.5 text-[12px] text-err ${className}`}>
      <div className="font-semibold">설정이 끝나지 않았어요 — 아래 항목이 필요한 단계는 실행되지 않아요</div>
      <ul className="mt-1 list-disc pl-5">
        {problems.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
      <div className="mt-1.5">
        <Link href="/settings" className="font-semibold text-err underline">
          설정 화면에서 키 넣기 →
        </Link>
        <span className="ml-2 text-muted">키 받는 방법은 docs/BETA_GUIDE.md 2절에 있어요.</span>
      </div>
    </div>
  );
}
