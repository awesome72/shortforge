"""화면에서 API 키를 넣고 확인한다 (베타 첫 실행의 .env 편집을 대신한다).

- 키 값은 어디로도 돌려주지 않는다. 목록은 "설정됨/비어 있음"만 알려 준다.
- 확인은 무료 호출만 쓴다: YouTube 1 unit, Gemini 1토큰(경량 모델), Cloudflare 모델 목록(Neurons 0),
  Pixabay 검색 1회. 결제가 연결된 Gemini 키(402)는 비용 ₩0 원칙에 어긋나므로 저장하지 않는다.
- 저장은 .env의 해당 줄만 바꾸고 나머지 줄과 주석은 그대로 둔다.
  파일이 없으면 .env.example에서 만든다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings
from app.quota import QuotaMeter
from app.support import scrub


@dataclass(frozen=True)
class KeyField:
    env: str
    attr: str
    label: str
    hint: str
    url: str
    group: str = "basic"  # basic | advanced (고급 모드, 유료) | video (영상 만들기, 유료)


FIELDS: tuple[KeyField, ...] = (
    KeyField(
        "YOUTUBE_API_KEY",
        "youtube_api_key",
        "YouTube Data API 키",
        "2단계 레퍼런스 탐색. Google Cloud Console → YouTube Data API v3 사용 "
        "→ 사용자 인증 정보 → API 키",
        "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
    ),
    KeyField(
        "GEMINI_API_KEY",
        "gemini_api_key",
        "Gemini API 키",
        "키워드·요인·전략 생성. 결제가 연결되지 않은 프로젝트의 키만 쓴다",
        "https://aistudio.google.com/apikey",
    ),
    KeyField(
        "CLOUDFLARE_ACCOUNT_ID",
        "cloudflare_account_id",
        "Cloudflare 계정 ID",
        "AI 이미지 생성(선택). dash.cloudflare.com 오른쪽의 계정 ID",
        "https://dash.cloudflare.com/",
    ),
    KeyField(
        "CLOUDFLARE_API_TOKEN",
        "cloudflare_api_token",
        "Cloudflare API 토큰",
        "AI 이미지 생성(선택). 내 프로필 → API 토큰 → 'Workers AI' 템플릿",
        "https://dash.cloudflare.com/profile/api-tokens",
    ),
    KeyField(
        "PIXABAY_API_KEY",
        "pixabay_api_key",
        "Pixabay API 키",
        "무료 사진(선택). 로그인 후 API 문서 페이지의 key 값",
        "https://pixabay.com/api/docs/",
    ),
    KeyField(
        "ANTHROPIC_API_KEY",
        "anthropic_api_key",
        "Anthropic API 키 (고급 모드, 유료)",
        "Claude로 성공 요인 분석·전략을 만든다. 쓴 만큼 Anthropic 계정에 과금된다. "
        "console.anthropic.com → API Keys",
        "https://console.anthropic.com/settings/keys",
        group="advanced",
    ),
    KeyField(
        "OPENAI_API_KEY",
        "openai_api_key",
        "OpenAI API 키 (고급 모드, 유료)",
        "GPT로 성공 요인 분석·전략을 만든다. 쓴 만큼 OpenAI 계정에 과금된다. "
        "platform.openai.com → API keys",
        "https://platform.openai.com/api-keys",
        group="advanced",
    ),
    KeyField(
        "OPENROUTER_API_KEY",
        "openrouter_api_key",
        "OpenRouter API 키 (고급 모드, 유료)",
        "키 하나로 Claude·GPT 등 여러 모델을 쓴다. 충전한 크레딧에서 차감된다. "
        "openrouter.ai → Keys",
        "https://openrouter.ai/settings/keys",
        group="advanced",
    ),
    KeyField(
        "HF_TOKEN",
        "hf_token",
        "Hugging Face 토큰 (영상 만들기, 유료)",
        "장면 그림을 영상으로 바꾼다. 쓴 만큼 Hugging Face 크레딧에서 나간다. "
        "Settings → Access Tokens에서 'Make calls to Inference Providers' 권한으로 만든다",
        "https://huggingface.co/settings/tokens",
        group="video",
    ),
)
BY_ENV = {f.env: f for f in FIELDS}

# 화면에서 고를 수 있는 이미지 방식. 그 밖의 값(comfyui 등)은 .env에서 직접 바꾼다
IMAGE_MODES = {
    "upload": "본인 사진만 (이미지를 만들지 않음)",
    "stock": "무료 사진 (Pixabay)",
    "cloudflare,stock": "AI 생성 (Cloudflare) → 실패·한도 초과 시 무료 사진",
    "video,cloudflare,stock": (
        "사람이 없는 장면은 무료 동영상 (Pixabay, 사진형 그림체일 때) → AI 생성 → 무료 사진"
    ),
}

VALUE = re.compile(r"[A-Za-z0-9._\-:]{6,200}")
PROBE_TIMEOUT = 30.0
UA = {"User-Agent": "ShortForge-keycheck"}


class KeyInputError(ValueError):
    pass


def status(settings: Settings) -> dict:
    return {
        "fields": [
            {
                "name": f.env,
                "label": f.label,
                "hint": f.hint,
                "url": f.url,
                "set": bool(getattr(settings, f.attr)),
                "group": f.group,
            }
            for f in FIELDS
        ],
        "image_mode": settings.image_mode,
        "image_modes": IMAGE_MODES,
        "llm_mode": settings.llm_mode,
        "advanced": advanced_status(settings),
        "video_gen": video_gen_status(settings),
    }


def video_gen_status(settings: Settings) -> dict:
    """영상 만들기(D19) 설정·오늘 사용액. 토큰 값은 넣지 않는다."""
    from app.spend import VIDEO_MODEL, VIDEO_PROVIDER, SpendMeter

    budget = settings.video_gen_daily_budget_usd
    return {
        "mode": settings.video_gen,
        "label": VIDEO_MODEL.label,
        "usd_per_sec": round(VIDEO_MODEL.usd_per_sec, 4),
        "usd_per_frame": VIDEO_MODEL.usd_per_frame,  # 화면이 서버와 같은 방식으로 값을 어림한다
        "fps": VIDEO_MODEL.fps,
        "budget_usd": budget,
        "spend": SpendMeter(settings.db_path, budget, VIDEO_PROVIDER).summary(),
    }


# ── 고급 모드 (D13) ─────────────────────────────────────


def advanced_status(settings: Settings) -> dict:
    """고급 모드 설정·오늘 사용액. 키 값은 넣지 않는다."""
    from app.spend import DEFAULT_MODEL, PRICES, PROVIDER_LABEL, SpendMeter

    mode = settings.llm_advanced
    provider = mode if mode != "off" else "anthropic"
    return {
        "mode": mode,
        "provider": provider,
        "providers": PROVIDER_LABEL,
        "defaults": DEFAULT_MODEL,
        "model": settings.advanced_model or DEFAULT_MODEL[provider],
        "effort": settings.advanced_effort,
        "tasks": sorted(settings.advanced_task_set),
        "budget_usd": settings.advanced_daily_budget_usd,
        "models": {
            p: {
                m: {"label": price.label, "input": price.input, "output": price.output}
                for m, price in models.items()
            }
            for p, models in PRICES.items()
        },
        "spend": SpendMeter(settings.db_path, settings.advanced_daily_budget_usd).summary(),
    }


def advanced_updates(mode: str, model: str, effort: str, budget: float) -> dict[str, str]:
    return {
        "LLM_ADVANCED": mode,
        "ADVANCED_MODEL": model,
        "ADVANCED_EFFORT": effort,
        "ADVANCED_DAILY_BUDGET_USD": f"{budget:g}",
    }


def apply_advanced(settings: Settings, mode: str, model: str, effort: str, budget: float) -> None:
    settings.llm_advanced = mode
    settings.advanced_model = model
    settings.advanced_effort = effort
    settings.advanced_daily_budget_usd = budget


def validate(values: dict[str, str]) -> dict[str, str]:
    """이름과 형식만 본다. 줄바꿈·따옴표가 들어가면 .env가 깨지므로 막는다."""
    out = {}
    for name, value in values.items():
        if name not in BY_ENV:
            raise KeyInputError(f"알 수 없는 항목: {name}")
        value = (value or "").strip()
        if not VALUE.fullmatch(value):
            raise KeyInputError(
                f"{BY_ENV[name].label}: 형식이 맞지 않다 "
                "(영문·숫자·-_.: 6~200자, 앞뒤 공백 없이 붙여 넣는다)"
            )
        out[name] = value
    return out


# ── 확인 (무료 호출) ─────────────────────────────────────


@dataclass
class Check:
    ok: bool | None  # None = 응답을 받지 못함(네트워크). 저장은 허용한다
    message: str


async def _youtube(c: httpx.AsyncClient, key: str, s: Settings) -> Check:
    meter = QuotaMeter(s.db_path, s.youtube_daily_unit_limit)
    meter.check("i18nLanguages")
    r = await c.get(
        "https://www.googleapis.com/youtube/v3/i18nLanguages",
        params={"part": "snippet", "hl": "ko", "key": key},
    )
    meter.record("i18nLanguages")
    if r.status_code == 200:
        return Check(True, "키 유효 (확인에 1 unit 사용)")
    return Check(False, _reason(r))


async def _gemini(c: httpx.AsyncClient, key: str, s: Settings) -> Check:
    model = s.gemini_model_light or s.gemini_model
    r = await c.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": key},
        json={
            "contents": [{"parts": [{"text": "ok"}]}],
            "generationConfig": {"maxOutputTokens": 1},
        },
    )
    msg = _reason(r)
    if r.status_code == 200:
        return Check(True, f"키 유효 ({model} 호출 성공)")
    if r.status_code == 402 or "billing" in msg.lower() or "prepay" in msg.lower():
        return Check(
            False,
            "결제가 연결된 프로젝트의 키다 — 모든 호출이 과금되므로 쓰지 않는다. "
            "결제가 없는 새 프로젝트에서 키를 다시 만든다",
        )
    if r.status_code == 429:
        return Check(None, "키는 받아들여졌지만 호출 한도에 걸렸다 — 잠시 후 다시 확인한다")
    return Check(False, msg)


async def _cloudflare(c: httpx.AsyncClient, account: str, token: str) -> Check:
    # 모델 목록 조회는 Neurons를 쓰지 않으면서 계정 ID·토큰·Workers AI 권한을 함께 확인한다
    r = await c.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/models/search",
        params={"per_page": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    if r.status_code == 200 and r.json().get("success"):
        return Check(True, "계정 ID·토큰 유효 (Workers AI 사용 가능, 하루 10,000 Neurons 무료)")
    if r.status_code in (401, 403):
        return Check(
            False, "토큰이 맞지 않거나 Workers AI 권한이 없다 — 'Workers AI' 템플릿으로 다시 만든다"
        )
    if r.status_code == 404:
        return Check(False, "계정 ID를 찾을 수 없다 — 대시보드의 계정 ID를 다시 복사한다")
    return Check(False, _reason(r))


async def _pixabay(c: httpx.AsyncClient, key: str) -> Check:
    r = await c.get("https://pixabay.com/api/", params={"key": key, "q": "office", "per_page": 3})
    if r.status_code == 200:
        return Check(True, "키 유효")
    return Check(False, f"키 확인 실패 (HTTP {r.status_code}) — key 값을 다시 복사한다")


def _reason(r: httpx.Response) -> str:
    try:
        body = r.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:300]
        if isinstance(body, dict) and body.get("errors"):
            return str(body["errors"][0].get("message", ""))[:300]
    except Exception:  # noqa: BLE001 - JSON이 아닌 응답
        pass
    return f"HTTP {r.status_code}"


async def check(
    values: dict[str, str],
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    anthropic_http_client=None,
) -> dict[str, dict]:
    """넣은 값만 확인한다. Cloudflare는 계정 ID·토큰을 함께 보므로 빠진 쪽은 저장된 값을 쓴다."""
    merged = {f.env: values.get(f.env) or getattr(settings, f.attr) for f in FIELDS}
    secrets = [v for v in [*values.values(), *merged.values()] if v]
    results: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT, transport=transport, headers=UA) as c:

        async def run(names: list[str], coro) -> None:
            try:
                res = await coro
            except httpx.HTTPError as e:
                res = Check(None, f"응답 없음 ({type(e).__name__}) — 인터넷 연결을 확인한다")
            except Exception as e:  # noqa: BLE001 - 쿼터 초과 등은 메시지로 보여 준다
                res = Check(None, str(e))
            for n in names:
                results[n] = {"ok": res.ok, "message": scrub(res.message, secrets)}

        if "YOUTUBE_API_KEY" in values:
            await run(["YOUTUBE_API_KEY"], _youtube(c, values["YOUTUBE_API_KEY"], settings))
        if "GEMINI_API_KEY" in values:
            await run(["GEMINI_API_KEY"], _gemini(c, values["GEMINI_API_KEY"], settings))
        cf = [n for n in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN") if n in values]
        if cf:
            account, token = merged["CLOUDFLARE_ACCOUNT_ID"], merged["CLOUDFLARE_API_TOKEN"]
            if not account or not token:
                missing = "API 토큰" if account else "계정 ID"
                for n in cf:
                    msg = f"Cloudflare {missing}도 넣어야 확인할 수 있다"
                    results[n] = {"ok": None, "message": msg}
            else:
                await run(cf, _cloudflare(c, account, token))
        if "PIXABAY_API_KEY" in values:
            await run(["PIXABAY_API_KEY"], _pixabay(c, values["PIXABAY_API_KEY"]))
        if "ANTHROPIC_API_KEY" in values:
            await run(
                ["ANTHROPIC_API_KEY"],
                _anthropic(values["ANTHROPIC_API_KEY"], anthropic_http_client),
            )
        for provider in ("openai", "openrouter"):
            env = f"{provider.upper()}_API_KEY"
            if env in values:
                await run([env], _openai_compat(provider, values[env], transport))
        if "HF_TOKEN" in values:
            await run(["HF_TOKEN"], _huggingface(values["HF_TOKEN"], transport))
    return results


async def _huggingface(token: str, transport) -> Check:
    from app.adapters.video_gen.hf import check_token

    ok, message = await check_token(token, transport)
    return Check(ok, message)


async def _openai_compat(provider: str, key: str, transport) -> Check:
    from app.adapters.llm.advanced.openai_compat import check_key

    ok, message = await check_key(provider, key, transport)
    return Check(ok, message)


async def _anthropic(key: str, http_client) -> Check:
    # 유료 SDK는 키를 확인할 때만 불러온다 (기본 설정에서는 로드하지 않는다, D13)
    from app.adapters.llm.advanced.anthropic_api import check_key

    ok, message = await check_key(key, http_client)
    return Check(ok, message)


# ── 저장 ────────────────────────────────────────────────


def write_env(path: Path, updates: dict[str, str]) -> None:
    """.env에서 바꿀 줄만 고친다. 없는 항목은 끝에 붙인다."""
    if path.exists():
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    else:
        example = path.with_name(".env.example")
        lines = example.read_text(encoding="utf-8").splitlines() if example.exists() else []
    pending = dict(updates)
    for i, line in enumerate(lines):
        is_setting = "=" in line and not line.lstrip().startswith("#")
        name = line.split("=", 1)[0].strip() if is_setting else ""
        if name in pending:
            lines[i] = f"{name}={pending.pop(name)}"
    lines += [f"{k}={v}" for k, v in pending.items()]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def apply(settings: Settings, keys: dict[str, str], image_mode: str | None) -> None:
    """실행 중인 서버의 설정을 바로 바꾼다 (다시 시작하지 않아도 된다)."""
    for name, value in keys.items():
        setattr(settings, BY_ENV[name].attr, value)
    if image_mode is not None:
        settings.image_mode = image_mode
