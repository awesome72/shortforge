"use client";

import { useState } from "react";

export interface Command {
  id: string;
  group: string;
  label: string;
  hint?: string;
  disabled?: boolean;
  run: () => void;
}

/** Ctrl+K 명령 창: 단계 이동·실행·설정을 글자로 찾아 Enter로 실행한다. 열 때마다 새로 그려 검색어가 비워진다 */
export function CommandPalette({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const q = query.trim().toLowerCase();
  const shown = commands.filter((c) => !q || `${c.group} ${c.label}`.toLowerCase().includes(q));
  const cur = Math.min(active, Math.max(0, shown.length - 1));

  const run = (c: Command | undefined) => {
    if (!c || c.disabled) return;
    onClose();
    c.run();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/55 px-4 pt-[14vh] backdrop-blur-[2px]"
      onPointerDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="명령"
        className="sf-toast w-full max-w-[520px] overflow-hidden rounded-[14px] border border-line-strong bg-surface shadow-[0_30px_80px_-20px_rgba(0,0,0,.85)]"
      >
        <input
          autoFocus
          role="combobox"
          aria-expanded="true"
          aria-controls="sf-commands"
          aria-activedescendant={shown[cur] ? `sf-cmd-${shown[cur].id}` : undefined}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") setActive((cur + 1) % Math.max(1, shown.length));
            else if (e.key === "ArrowUp") setActive((cur - 1 + shown.length) % Math.max(1, shown.length));
            else if (e.key === "Enter") run(shown[cur]);
            else if (e.key === "Escape") onClose();
            else return;
            e.preventDefault();
          }}
          placeholder="무엇을 할까요? (단계 이름, 실행, 설정…)"
          className="w-full border-b border-line bg-transparent px-[18px] py-4 text-[15px] text-ink outline-none placeholder:text-muted-2"
        />
        <ul id="sf-commands" role="listbox" className="max-h-[50vh] overflow-y-auto py-1.5">
          {shown.length === 0 && <li className="px-[18px] py-3 text-[13px] text-muted">맞는 명령이 없어요</li>}
          {shown.map((c, i) => (
            <li
              key={c.id}
              id={`sf-cmd-${c.id}`}
              role="option"
              aria-selected={i === cur}
              aria-disabled={c.disabled}
              onPointerMove={() => setActive(i)}
              onClick={() => run(c)}
              className={`mx-1.5 flex cursor-pointer items-center gap-3 rounded-[8px] px-3 py-2.5 text-[13.5px] ${i === cur ? "bg-card text-ink" : "text-ink-2"} ${c.disabled ? "cursor-not-allowed opacity-45" : ""}`}
            >
              <span className="w-9 flex-none text-[11.5px] text-faint">{c.group}</span>
              <span className="min-w-0 flex-1 truncate">{c.label}</span>
              {c.hint && <kbd className="sf-kbd">{c.hint}</kbd>}
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-[18px] py-2.5 text-[11.5px] text-muted">
          <span>
            <kbd className="sf-kbd">1</kbd>–<kbd className="sf-kbd">7</kbd> 단계 이동
          </span>
          <span>
            <kbd className="sf-kbd">Ctrl</kbd> <kbd className="sf-kbd">Enter</kbd> 이 단계 실행
          </span>
          <span>
            <kbd className="sf-kbd">Ctrl</kbd> <kbd className="sf-kbd">K</kbd> 명령 창
          </span>
        </div>
      </div>
    </div>
  );
}
