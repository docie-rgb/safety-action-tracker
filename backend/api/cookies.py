"""세션 쿠키 설정. 토큰은 HttpOnly 쿠키에만 두어 브라우저 자바스크립트가 읽을 수 없게 한다."""

from fastapi import Response

from backend import config
from backend.supabase_auth import Session

ACCESS_COOKIE = "sat_access"
REFRESH_COOKIE = "sat_refresh"

_PATH = "/api"  # API 요청에만 전송 (정적 파일 요청에는 붙지 않음)
_REFRESH_MAX_AGE = 7 * 24 * 60 * 60  # 7일


def set_session_cookies(response: Response, session: Session) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        session.access_token,
        max_age=session.expires_in,
        path=_PATH,
        httponly=True,  # JS 에서 document.cookie 로 읽을 수 없음
        secure=config.COOKIE_SECURE,  # true 면 HTTPS 에서만 전송
        samesite="lax",  # 다른 사이트에서 보낸 POST/PATCH/DELETE·fetch 에는 붙지 않음
    )
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh_token,
        max_age=_REFRESH_MAX_AGE,
        path=_PATH,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="strict",  # 다른 사이트에서 시작된 요청에는 절대 붙지 않음
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path=_PATH, httponly=True, secure=config.COOKIE_SECURE, samesite="lax")
    response.delete_cookie(REFRESH_COOKIE, path=_PATH, httponly=True, secure=config.COOKIE_SECURE, samesite="strict")
