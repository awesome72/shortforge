import { SCOPE_LABEL } from "@/lib/labels";
import type { Factor } from "@/lib/types";

/** 영상 공식 카드의 내용: 어디서 보였는지와 시작·전개·감정·끝맺음 */
export function Formula({ factor: f }: { factor: Factor }) {
  const rows = [
    ["시작", f.hook_type],
    ["전개", f.structure],
    ["감정", f.emotion],
    ["끝맺음", f.ending],
  ] as const;
  return (
    <>
      {f.scope && <div className="text-[13px] font-semibold text-accent">{SCOPE_LABEL[f.scope]}</div>}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[12.5px] text-muted">
        {rows.map(
          ([label, value]) =>
            value && (
              <div key={label} className="contents">
                <dt>{label}</dt>
                <dd className="text-ink-2">{value}</dd>
              </div>
            ),
        )}
      </dl>
    </>
  );
}
