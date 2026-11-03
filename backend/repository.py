"""Supabase(PostgreSQL) 저장소. Supabase Data API(PostgREST, /rest/v1)를 HTTP로 호출한다.

  - apikey 헤더        : publishable 키 (어느 프로젝트에 요청하는지 식별)
  - Authorization 헤더 : 로그인한 사용자의 액세스 토큰
DB는 토큰으로 요청자를 알아내 auth.uid() 를 정하고 RLS 정책·컬럼 권한을 적용한다.

따라서 이 파일은 사용자 ID·사업장 ID로 행을 걸러내지 않고, 그 값을 보내지도 않는다.
  - 조회 범위 제한          → RLS 정책 (supabase/schema.sql)
  - reported_by / 사업장    → 컬럼 기본값 auth.uid() / private.my_org()
  - 관리자 전용 필드·역할   → 컬럼 권한 + RLS
RLS 를 우회하는 secret/service_role 키는 사용하지 않는다.
"""

import uuid

import httpx

from backend import domain
from backend.domain import CurrentUser

REPORT_COLUMNS = (
    "id,organization_id,reported_by,area,hazard,action,status,due_date,completed_at,created_at,updated_at,"
    "reporter:profiles(display_name)"  # 복합 외래키로 연결된 신고자 이름 (RLS 로 보이는 경우에만)
)
UPDATABLE_FIELDS = {"action", "status", "due_date"}

# PostgreSQL 오류 코드
_CHECK_VIOLATION = "23514"
_RLS_OR_PRIVILEGE_VIOLATION = "42501"
_RAISE_EXCEPTION = "P0001"


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def _report(row: dict) -> dict:
    reporter = row.pop("reporter", None) or {}
    row["reporter_name"] = reporter.get("display_name")
    return row


class SupabaseRepository:
    def __init__(self, url: str, publishable_key: str, transport: httpx.BaseTransport | None = None):
        if not url or not publishable_key:
            raise RuntimeError("SUPABASE_URL 과 SUPABASE_PUBLISHABLE_KEY 가 필요합니다 (.env).")
        self._key = publishable_key
        # 사용자 토큰은 클라이언트에 저장하지 않고 요청마다 헤더로 넣는다 (여러 사용자 요청이 섞이지 않게).
        self._http = httpx.Client(base_url=f"{url}/rest/v1", timeout=10.0, transport=transport)

    def _request(self, user: CurrentUser, method: str, path: str, *, params=None, json=None):
        if not user.access_token:
            raise domain.Unauthorized()
        headers = {"apikey": self._key, "Authorization": f"Bearer {user.access_token}"}
        if method in ("POST", "PATCH", "DELETE"):
            headers["Prefer"] = "return=representation"  # 변경된 행을 응답으로 돌려받는다 (0건이면 [])
        try:
            res = self._http.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError:
            raise domain.StorageUnavailable() from None

        if res.is_success:
            return res.json() if res.content else []

        body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
        code = body.get("code") if isinstance(body, dict) else None
        if res.status_code == 401:
            raise domain.Unauthorized("로그인이 만료되었습니다. 다시 로그인하세요.")
        if code == _RAISE_EXCEPTION and body.get("hint") == "report_limit":
            raise domain.TooManyRequests("이 계정의 신고 가능 건수를 초과했습니다. 관리자에게 데모 초기화를 요청하세요.")
        if code == _CHECK_VIOLATION:
            raise domain.ValidationError("저장 규칙에 맞지 않습니다. 완료 처리에는 개선조치 내용이 필요합니다.")
        if code == _RLS_OR_PRIVILEGE_VIOLATION or res.status_code == 403:
            raise domain.PermissionDenied()
        # 그 밖의 오류는 내부 정보(SQL 등)를 사용자에게 노출하지 않는다.
        raise domain.StorageUnavailable(f"데이터 저장소 오류 (HTTP {res.status_code})")

    # ---------- profiles ----------

    def get_profile(self, user: CurrentUser) -> dict | None:
        """로그인한 사용자 자신의 역할·사업장. RLS 로 본인 행은 항상 보인다."""
        rows = self._request(
            user,
            "GET",
            "/profiles",
            params={"select": "role,organization_id,display_name", "user_id": f"eq.{user.id}"},
        )
        return rows[0] if rows else None

    # ---------- hazard_reports ----------

    def list_reports(self, user: CurrentUser, status: str | None = None) -> list[dict]:
        params = {"select": REPORT_COLUMNS, "order": "created_at.desc,id.desc"}
        if status is not None:
            params["status"] = f"eq.{domain.clean_status(status)}"
        return [_report(r) for r in self._request(user, "GET", "/hazard_reports", params=params)]

    def get_report(self, user: CurrentUser, report_id: str) -> dict:
        if not _is_uuid(report_id):
            raise domain.NotFound()
        rows = self._request(
            user, "GET", "/hazard_reports", params={"select": REPORT_COLUMNS, "id": f"eq.{report_id}"}
        )
        if not rows:  # 없는 신고이거나 RLS 때문에 보이지 않는(남의) 신고
            raise domain.NotFound()
        return _report(rows[0])

    def create_report(self, user: CurrentUser, area: str, hazard: str) -> dict:
        values = {
            "area": domain.clean_text(area, "작업구역", domain.AREA_MAX),
            "hazard": domain.clean_text(hazard, "위험요인 설명", domain.HAZARD_MAX),
        }  # reported_by·organization_id·status 는 보내지 않는다 (DB 기본값 / 권한 없음)
        rows = self._request(user, "POST", "/hazard_reports", params={"select": REPORT_COLUMNS}, json=values)
        return _report(rows[0])

    def update_report(self, user: CurrentUser, report_id: str, changes: dict) -> dict:
        unknown = set(changes) - UPDATABLE_FIELDS
        if unknown:
            raise domain.ValidationError(f"수정할 수 없는 필드: {', '.join(sorted(unknown))}")
        if not changes:
            raise domain.ValidationError("수정할 내용이 없습니다.")

        values = {}
        if "action" in changes:
            values["action"] = domain.clean_optional_text(changes["action"], "개선조치 내용", domain.ACTION_MAX)
        if "status" in changes:
            values["status"] = domain.clean_status(changes["status"])
        if "due_date" in changes:
            values["due_date"] = domain.clean_due_date(changes["due_date"])

        if not _is_uuid(report_id):
            raise domain.NotFound()
        rows = self._request(
            user,
            "PATCH",
            "/hazard_reports",
            params={"id": f"eq.{report_id}", "select": REPORT_COLUMNS},
            json=values,
        )
        if not rows:  # 없는 신고, 또는 RLS 로 수정할 수 없는 신고
            raise domain.NotFound()
        return _report(rows[0])

    def delete_report(self, user: CurrentUser, report_id: str) -> None:
        if not _is_uuid(report_id):
            raise domain.NotFound()
        rows = self._request(user, "DELETE", "/hazard_reports", params={"id": f"eq.{report_id}", "select": "id"})
        if not rows:
            raise domain.NotFound()

    def reset_demo(self, user: CurrentUser) -> int:
        """관리자 전용 RPC. 함수 안에서 DB가 역할을 다시 확인한다."""
        return int(self._request(user, "POST", "/rpc/reset_demo_data", json={}))
