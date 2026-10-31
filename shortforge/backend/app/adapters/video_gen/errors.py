"""영상 만들기 오류. API가 httpx 어댑터(hf.py)를 불러오지 않고도 잡을 수 있게 따로 둔다."""


class VideoGenError(RuntimeError):
    """사용자에게 그대로 보여 줄 수 있는 실패 이유 (토큰·이미지 내용을 넣지 않는다)."""
