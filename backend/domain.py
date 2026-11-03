"""DB와 무관한 업무 규칙: 현재 사용자, 입력 정규화, 도메인 오류."""

import re
from dataclasses import dataclass, field
from datetime import date

ROLES = ("worker", "manager")
STATUSES = ("received", "in_progress", "completed")

AREA_MAX = 100
HAZARD_MAX = 1000
ACTION_MAX = 1000


@dataclass(frozen=True)
class CurrentUser:
    """백엔드가 검증한 로그인 사용자.

    id·email 은 Supabase Auth 가 토큰을 검증해 돌려준 값이고, role·organization_id 는
    그 사용자 토큰으로 DB(profiles)에서 읽은 값이다. 클라이언트가 보낸 role/user_id 는 절대 사용하지 않는다.
    access_token 은 DB 요청에 그대로 실어 보내 RLS 가 이 사용자로 적용되게 한다 (repr=False: 로그에 찍히지 않게).
    """

    id: str
    email: str | None = None
    access_token: str | None = field(default=None, repr=False)
    role: str | None = None
    organization_id: str | None = None
    display_name: str | None = None

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"

    def public(self) -> dict:
        """화면에 내려보내는 사용자 정보 (토큰 제외)."""
        return {
            "email": self.email,
            "role": self.role,
            "display_name": self.display_name,
            "organization_id": self.organization_id,
        }


class DomainError(Exception):
    """API 계층이 HTTP 상태코드로 바꿔 응답하는 오류의 기반 클래스."""


class ValidationError(DomainError):
    pass


class NotFound(DomainError):
    def __init__(self, message: str = "신고를 찾을 수 없습니다."):
        super().__init__(message)


class Unauthorized(DomainError):
    def __init__(self, message: str = "로그인이 필요합니다."):
        super().__init__(message)


class PermissionDenied(DomainError):
    def __init__(self, message: str = "권한이 없습니다."):
        super().__init__(message)


class TooManyRequests(DomainError):
    def __init__(self, message: str = "요청이 너무 많습니다. 잠시 후 다시 시도하세요."):
        super().__init__(message)


class StorageUnavailable(DomainError):
    def __init__(self, message: str = "데이터 저장소에 연결할 수 없습니다. 잠시 후 다시 시도하세요."):
        super().__init__(message)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clean_text(value: str | None, label: str, max_len: int) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValidationError(f"{label}을(를) 입력하세요.")
    if len(cleaned) > max_len:
        raise ValidationError(f"{label}은(는) {max_len}자 이하로 입력하세요.")
    return cleaned


def clean_optional_text(value: str | None, label: str, max_len: int) -> str | None:
    """빈 값은 NULL(지움)."""
    if value is None or not value.strip():
        return None
    return clean_text(value, label, max_len)


def clean_due_date(value: str | None) -> str | None:
    """조치기한은 선택사항. 빈 값은 NULL, 그 외에는 실제 존재하는 YYYY-MM-DD 날짜만 허용."""
    if value is None or value == "":
        return None
    if not _DATE_RE.match(value):
        raise ValidationError("조치기한은 YYYY-MM-DD 형식이어야 합니다.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValidationError("존재하지 않는 날짜입니다.") from None
    return value


def clean_status(value: str) -> str:
    if value not in STATUSES:
        raise ValidationError("상태는 received, in_progress, completed 중 하나여야 합니다.")
    return value
