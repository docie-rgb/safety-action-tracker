"""공개 데모 남용 방지용 단순 요청 제한 (프로세스 메모리, 고정 길이 슬라이딩 윈도).

Render Free 는 인스턴스 1개이므로 메모리 방식으로 충분하다. 재시작하면 카운트는 초기화된다.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from backend import domain


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise domain.TooManyRequests()
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_ip(request: Request) -> str:
    # Render 는 프록시 뒤에서 실제 접속 IP 를 X-Forwarded-For 로 전달한다.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


login_limiter = RateLimiter(limit=20, window_seconds=600)  # IP당 10분에 로그인 20회
report_limiter = RateLimiter(limit=20, window_seconds=600)  # 사용자당 10분에 신고 20건
