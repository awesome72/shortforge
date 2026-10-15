"""Step 7-3 TTS 블라인드 테스트 키트: 음성 후보를 섞은 듣기 페이지를 만든다.

- 후보: Edge-TTS 한국어 음성 3종 × 속도 2가지. 라벨(A~F)은 무작위로 섞는다.
- 숫자 읽기 점검: 대본의 숫자를 한글로 바꾸지 않기로 했으므로(자막이 TTS 어절에서 나옴)
  Edge-TTS가 "3개월", "10분", "2층" 등을 맞게 읽는지 귀로 확인한다.

사용법 (shortforge/backend에서):
    uv run python ../scripts/tts_blind_test.py
    → shortforge/data/blind_test/index.html 을 브라우저로 연다 (결과는 브라우저에 저장, JSON으로 내보내기)
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.tts.edge import EdgeTTSAdapter  # noqa: E402

VOICES = ["ko-KR-SunHiNeural", "ko-KR-InJoonNeural", "ko-KR-HyunsuMultilingualNeural"]
RATES = ["+0%", "+10%"]
SCRIPT = (
    "3개월 전의 저는, 계단 두 층에도 숨이 찼어요. "
    "그래서 딱 10분만 하기로 했어요. 스쿼트, 플랭크, 런지. 이 세 가지만요. "
    "오늘 퇴근길에, 같이 시작해 볼까요?"
)
NUMBER_CHECKS = [
    ("3개월", "삼 개월"),
    ("10분", "십 분"),
    ("2층", "이 층"),
    ("30대 직장인", "삼십 대"),
    ("5가지", "다섯 가지"),
    ("11시 40분", "열한 시 사십 분"),
    ("주 3회", "주 삼 회"),
    ("1.5배", "일 점 오 배"),
    ("100km", "백 킬로미터"),
    ("2026년 10월", "이천이십육 년 시월"),
]


async def main() -> int:
    out = ROOT / "data" / "blind_test"
    out.mkdir(parents=True, exist_ok=True)
    tts = EdgeTTSAdapter()
    rng = random.Random()

    variants = [(v, r) for v in VOICES for r in RATES]
    rng.shuffle(variants)
    labels = "ABCDEFGH"
    samples = []
    for i, (voice, rate) in enumerate(variants):
        res = await tts.synthesize(SCRIPT, voice, rate, out / f"sample_{labels[i]}.mp3")
        samples.append({"label": labels[i], "file": res.path.name, "voice": voice, "rate": rate,
                        "sec": res.duration_sec})  # fmt: skip
        print(f"  {labels[i]} 생성 ({res.duration_sec:.1f}초)")

    checks = []
    for i, (text, expect) in enumerate(NUMBER_CHECKS):
        res = await tts.synthesize(f"{text}.", VOICES[0], "+0%", out / f"num_{i}.mp3")
        checks.append({"file": res.path.name, "text": text, "expect": expect})
    print(f"  숫자 읽기 {len(checks)}개 생성")

    html = PAGE.replace("__SAMPLES__", json.dumps(samples, ensure_ascii=False)).replace(
        "__CHECKS__", json.dumps(checks, ensure_ascii=False)
    ).replace("__SCRIPT__", SCRIPT)
    (out / "index.html").write_text(html, encoding="utf-8")
    print(f"\n열기: {out / 'index.html'}")
    return 0


PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TTS 블라인드 테스트</title>
<style>
:root{--bg:#F3F1EC;--card:#fff;--line:#D9D5CC;--ink:#17191E;--muted:#5C5F66;--accent:#2448C9;--ok:#1F6B3A;--warn:#B4501C}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 "Malgun Gothic",sans-serif}
main{max-width:860px;margin:0 auto;padding:28px 16px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:8px 0}
.row{display:flex;flex-wrap:wrap;align-items:center;gap:12px}.lab{font:700 20px monospace;width:28px}
audio{height:36px;max-width:100%}label{white-space:nowrap}textarea{width:100%;min-height:54px;border:1px solid var(--line);border-radius:8px;padding:6px}
button{min-height:40px;padding:0 16px;border-radius:8px;border:0;background:var(--accent);color:#fff;font-weight:600;cursor:pointer}
button.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}pre{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;overflow:auto}
.ok{color:var(--ok)}.bad{color:var(--warn)}
</style></head><body><main>
<h1>TTS 블라인드 테스트</h1>
<p class="muted">같은 대본을 6가지 음성·속도로 읽었다. 라벨은 무작위로 섞여 있다. 각 샘플의 자연스러움(1~5)을 매기고, 숏폼 내레이션으로 쓰고 싶은 것을 고른다.</p>
<div class="card muted">대본: __SCRIPT__</div>
<h2>1. 음성 비교</h2><div id="samples"></div>
<h2>2. 숫자 읽기 점검 (기본 음성)</h2>
<p class="muted">들리는 대로 맞으면 ✔, 틀리게 읽으면 ✘. 틀린 항목이 많으면 대본 숫자 한글화를 다시 검토한다.</p>
<div id="checks"></div>
<h2>3. 결과</h2>
<div class="row"><button id="reveal">정답(음성·속도) 공개</button><button class="ghost" id="export">결과 JSON 복사</button></div>
<pre id="out" hidden></pre>
<script>
const SAMPLES=__SAMPLES__, CHECKS=__CHECKS__, KEY="sf-blind-"+SAMPLES.map(s=>s.file).join();
let st={}; try{st=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}};
const sw=document.getElementById("samples"), cw=document.getElementById("checks");
SAMPLES.forEach(s=>{const d=document.createElement("div");d.className="card";
 d.innerHTML=`<div class="row"><span class="lab">${s.label}</span><audio controls preload="none" src="${s.file}"></audio>
 <span>${[1,2,3,4,5].map(n=>`<label><input type="radio" name="r${s.label}" value="${n}"> ${n}</label>`).join(" ")}</span>
 <label><input type="radio" name="pick" value="${s.label}"> 이걸로</label></div>
 <textarea placeholder="메모 (예: 억양 어색, 너무 빠름)"></textarea><div class="muted reveal" hidden></div>`;
 d.querySelectorAll(`input[name=r${s.label}]`).forEach(i=>{i.checked=st["r"+s.label]==i.value;i.onchange=()=>{st["r"+s.label]=i.value;save()}});
 const p=d.querySelector("input[name=pick]");p.checked=st.pick===s.label;p.onchange=()=>{st.pick=s.label;save()};
 const t=d.querySelector("textarea");t.value=st["m"+s.label]||"";t.oninput=()=>{st["m"+s.label]=t.value;save()};
 d.querySelector(".reveal").textContent=`${s.voice.replace("ko-KR-","").replace("Neural","")} · 속도 ${s.rate} · ${s.sec.toFixed(1)}초`;
 sw.appendChild(d)});
CHECKS.forEach((c,i)=>{const d=document.createElement("div");d.className="card row";
 d.innerHTML=`<audio controls preload="none" src="${c.file}"></audio><b>${c.text}</b><span class="muted">기대: ${c.expect}</span>
 <label><input type="radio" name="n${i}" value="ok"> <span class="ok">✔</span></label><label><input type="radio" name="n${i}" value="bad"> <span class="bad">✘</span></label>`;
 d.querySelectorAll(`input[name=n${i}]`).forEach(x=>{x.checked=st["n"+i]==x.value;x.onchange=()=>{st["n"+i]=x.value;save()}});
 cw.appendChild(d)});
document.getElementById("reveal").onclick=()=>document.querySelectorAll(".reveal").forEach(e=>e.hidden=false);
document.getElementById("export").onclick=async()=>{
 const res={samples:SAMPLES.map(s=>({label:s.label,voice:s.voice,rate:s.rate,score:+st["r"+s.label]||null,memo:st["m"+s.label]||""})),
  pick:st.pick?SAMPLES.find(s=>s.label===st.pick):null,
  numbers:CHECKS.map((c,i)=>({text:c.text,expect:c.expect,result:st["n"+i]||null}))};
 const o=document.getElementById("out");o.hidden=false;o.textContent=JSON.stringify(res,null,2);
 try{await navigator.clipboard.writeText(o.textContent)}catch(e){}};
</script></main></body></html>
"""

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
