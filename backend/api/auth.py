"""로그인·데모 로그인·로그아웃·토큰 갱신·로그인 상태 확인 API. 응답 본문에는 토큰을 절대 넣지 않는다."""

from typing import Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend import config, domain
from backend.api.cookies import ACCESS_COOKIE, REFRESH_COOKIE, clear_session_cookies, set_session_cookies
from backend.api.deps import get_auth, with_profile
from backend.domain import CurrentUser
from backend.ratelimit import client_ip, login_limiter
from backend.supabase_auth import Session

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class DemoLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # 어떤 데모 계정으로 로그인할지만 고른다. 권한은 그 계정의 DB 역할(profiles.role)로 정해진다.
    role: Literal["worker", "manager"]


def _user_of(session: Session) -> CurrentUser:
    return with_profile(CurrentUser(id=session.user_id, email=session.email, access_token=session.access_token))


def _sign_in(email: str, password: str, response: Response) -> dict:
    auth = get_auth()
    session = auth.sign_in(email, password)
    try:
        user = _user_of(session)
    except domain.PermissionDenied:
        # 역할이 없는 계정은 세션을 바로 끝내고 쿠키를 주지 않는다.
        try:
            auth.sign_out(session.access_token)
        except domain.DomainError:
            pass
        raise
    set_session_cookies(response, session)
    return {"authenticated": True, "user": user.public()}


@router.get("/me")
def me(request: Request, response: Response):
    """화면이 처음 열릴 때 호출: 지금 누구로(어떤 역할로) 로그인되어 있는지.

    액세스 토큰이 만료됐어도 리프레시 쿠키가 유효하면 조용히 갱신한다.
    """
    auth = get_auth()
    token = request.cookies.get(ACCESS_COOKIE)
    if token:
        try:
            user = with_profile(auth.get_user(token))
            return {"authenticated": True, "user": user.public()}
        except domain.Unauthorized:
            pass
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if refresh_token:
        try:
            session = auth.refresh(refresh_token)
            user = _user_of(session)
            set_session_cookies(response, session)
            return {"authenticated": True, "user": user.public()}
        except domain.Unauthorized:
            clear_session_cookies(response)
    return {"authenticated": False, "user": None}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    login_limiter.hit(client_ip(request))
    return _sign_in(body.email.strip(), body.password, response)


@router.post("/auth/demo")
def demo_login(body: DemoLoginIn, request: Request, response: Response):
    """서버가 보관한 데모 계정으로 실제 Supabase 로그인을 한다. 비밀번호는 브라우저로 가지 않는다."""
    login_limiter.hit(client_ip(request))
    email, password = config.DEMO_ACCOUNTS[body.role]
    if not email or not password:
        raise domain.StorageUnavailable("데모 계정이 설정되지 않았습니다.")
    return _sign_in(email, password, response)


@router.post("/auth/refresh")
def refresh(request: Request, response: Response):
    """액세스 토큰 만료(401) 시 화면이 호출한다. 리프레시 토큰을 새 토큰 한 쌍으로 교환한다."""
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise domain.Unauthorized()
    try:
        session = get_auth().refresh(refresh_token)
    except domain.Unauthorized:
        # 쿠키를 지운 응답을 직접 돌려준다 (예외로 끝내면 쿠키 삭제가 적용되지 않는다).
        expired = JSONResponse(status_code=401, content={"detail": "로그인이 만료되었습니다. 다시 로그인하세요."})
        clear_session_cookies(expired)
        return expired
    set_session_cookies(response, session)
    return {"ok": True}


@router.post("/auth/logout", status_code=204)
def logout(request: Request):
    """Supabase 세션을 끝내고(리프레시 토큰 무효화) 쿠키를 지운다. Supabase 호출이 실패해도 쿠키는 지운다."""
    token = request.cookies.get(ACCESS_COOKIE)
    if token:
        try:
            get_auth().sign_out(token)
        except domain.DomainError:
            pass
    response = Response(status_code=204)
    clear_session_cookies(response)
    return response
