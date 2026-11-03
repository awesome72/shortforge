"""인증 없는 로컬 앱을 다른 사이트에서 지킨다.

서버는 127.0.0.1에만 뜨지만 사용자의 브라우저는 어떤 사이트에서든 이 주소로 요청을 보낼 수 있다.
- Origin: 다른 사이트의 페이지가 보낸 변경 요청을 막는다. 브라우저는 교차 출처 POST에 Origin을
  붙이고, 페이지가 이를 지울 수 없다. 스크립트·CLI는 Origin이 없어 그대로 지나간다.
- Host: 다른 도메인이 이 PC 주소를 가리키게 바꾸면(DNS rebinding) 같은 출처처럼 보이므로
  Host가 그 도메인인 요청을 막는다.

BaseHTTPMiddleware는 SSE 스트림을 감싸므로 쓰지 않고 ASGI로 직접 쓴다.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings

READ_ONLY = {"GET", "HEAD", "OPTIONS"}


def host_name(value: str) -> str:
    """Host 헤더에서 포트와 대괄호를 뺀다."""
    try:
        return (urlsplit(f"//{value}").hostname or "").lower()
    except ValueError:  # "[::1" 같은 깨진 값
        return ""


class LocalRequestGuard:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    def _hosts(self) -> set[str]:
        hosts = {h.strip("[]").lower() for h in self.settings.allowed_hosts}
        hosts |= {urlsplit(o).hostname or "" for o in self.settings.cors_origins}
        return hosts - {""}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            reason = None
            if host_name(headers.get("host", "")) not in self._hosts():
                reason = "이 PC의 주소로만 접속할 수 있어요"
            elif (
                scope["method"] not in READ_ONLY
                and origin
                and origin not in self.settings.cors_origins
            ):
                reason = "웹 화면에서만 할 수 있어요"
            if reason:
                await JSONResponse({"detail": reason}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
