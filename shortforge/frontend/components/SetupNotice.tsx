import Link from "next/link";
import type { AppConfig } from "@/lib/types";

/** .env에 빠진 키가 있으면 무엇을 채울지 알려 준다. 서버는 떠 있고, 그 키가 필요한 단계만 실패한다. */
export function SetupNotice({ config, className = "" }: { config: AppConfig | null; className?: string }) {
  const problems = config?.setup_problems ?? [];
  if (problems.length === 0) return null;
  return (
    <div className={`border-b border-err/30 bg-err-tint px-7 py-2.5 text-[12px] text-err ${className}`}>
      <div className="font-semibold">설정이 끝나지 않았다 — 아래 항목이 필요한 단계는 실행되지 않는다</div>
      <ul className="mt-1 list-disc pl-5">
        {problems.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
      <div className="mt-1.5">
        <Link href="/settings" className="font-semibold text-err underline">
          설정 화면에서 키 넣기 →
        </Link>
        <span className="ml-2 text-muted">키 받는 방법은 docs/BETA_GUIDE.md 2절.</span>
      </div>
    </div>
  );
}
