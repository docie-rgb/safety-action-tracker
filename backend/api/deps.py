"""라우터가 주입받는 의존성: 저장소, 인증 클라이언트, 현재 사용자, 관리자 확인."""

from dataclasses import replace
from functools import lru_cache

from fastapi import Depends, Request

from backend import config, domain
from backend.api.cookies import ACCESS_COOKIE
from backend.domain import CurrentUser
from backend.repository import SupabaseRepository
from backend.supabase_auth import SupabaseAuth


@lru_cache
def get_repo() -> SupabaseRepository:
    return SupabaseRepository(config.SUPABASE_URL, config.SUPABASE_PUBLISHABLE_KEY)


@lru_cache
def get_auth() -> SupabaseAuth:
    return SupabaseAuth(config.SUPABASE_URL, config.SUPABASE_PUBLISHABLE_KEY)


def with_profile(user: CurrentUser) -> CurrentUser:
    """검증된 사용자에 DB의 역할·사업장을 붙인다. 프로필이 없는 계정은 이 서비스를 쓸 수 없다."""
    profile = get_repo().get_profile(user)
    if not profile or profile.get("role") not in domain.ROLES:
        raise domain.PermissionDenied("역할이 지정되지 않은 계정입니다. 관리자에게 문의하세요.")
    return replace(
        user,
        role=profile["role"],
        organization_id=profile["organization_id"],
        display_name=profile.get("display_name"),
    )


def get_current_user(request: Request) -> CurrentUser:
    """요청한 사용자를 결정한다.

    sat_access 쿠키의 토큰을 Supabase Auth 에 검증받고, 그 토큰으로 DB에서 역할을 읽는다.
    클라이언트가 보낸 role·user_id 같은 값은 어디에서도 사용하지 않는다.
    """
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise domain.Unauthorized()
    return with_profile(get_auth().get_user(token))


def require_manager(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """관리자 전용 API 의 1차 방어. DB 의 RLS·컬럼 권한이 2차로 같은 규칙을 강제한다."""
    if not user.is_manager:
        raise domain.PermissionDenied("안전관리자만 사용할 수 있는 기능입니다.")
    return user
