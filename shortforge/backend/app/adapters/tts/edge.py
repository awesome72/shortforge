"""Edge-TTS 어댑터. 음성(mp3)과 어절 단위 타이밍(JSON)을 함께 만든다.

주의: Edge-TTS는 비공식 엔드포인트다. 상업적 이용 시 MeloTTS로 전환한다 (PRD §8).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import edge_tts

from app.adapters.base import TTSAdapter, TTSResult
from app.media import probe_duration

TICKS_PER_SEC = 10_000_000  # Edge-TTS offset/duration 단위는 100ns
RETRIES = 3


class EdgeTTSAdapter(TTSAdapter):
    async def synthesize(self, text: str, voice: str, rate: str, out_path: Path) -> TTSResult:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        words_path = out_path.with_suffix(".words.json")

        last_error: Exception | None = None
        for attempt in range(RETRIES):
            try:
                words = await self._stream(text, voice, rate, out_path)
                break
            except (edge_tts.exceptions.EdgeTTSException, OSError, TimeoutError) as e:
                last_error = e
                await asyncio.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"Edge-TTS 합성 실패 ({RETRIES}회 시도): {last_error}")

        words_path.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        return TTSResult(
            path=out_path,
            duration_sec=round(await probe_duration(out_path), 3),
            words_path=words_path,
        )

    async def _stream(self, text: str, voice: str, rate: str, out_path: Path) -> list[dict]:
        communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
        words: list[dict] = []
        with out_path.open("wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / TICKS_PER_SEC
                    words.append(
                        {
                            "text": chunk["text"],
                            "start": round(start, 3),
                            "end": round(start + chunk["duration"] / TICKS_PER_SEC, 3),
                        }
                    )
        if out_path.stat().st_size == 0:
            raise edge_tts.exceptions.NoAudioReceived("빈 오디오")
        return words
