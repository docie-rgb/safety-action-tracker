"""SupabaseRepository 단위 테스트 — HTTP 요청/응답을 가짜(MockTransport)로 대신한다.

이 테스트가 증명하는 것:
  - DB에 보내는 요청의 모양 (사용자 토큰, 본문에 reported_by/status 없음, 필터 파라미터)
  - DB 오류 코드를 도메인 오류로 바꾸는 규칙
"""

import json
import uuid

import httpx
import pytest

from backend import domain
from backend.domain import CurrentUser
from backend.repository import SupabaseRepository

KEY = "sb_publishable_test"
TOKEN = "user-access-token-for-test"
USER = CurrentUser(id=str(uuid.uuid4()), email="w@example.com", access_token=TOKEN, role="worker")
RID = str(uuid.uuid4())
ROW = {"id": RID, "area": "A", "hazard": "B", "status": "received", "reporter": {"display_name": "작업자"}}


class FakePostgrest:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        status, body = self.responses.pop(0)
        return httpx.Response(status, json=body)


def make_repo(*responses):
    fake = FakePostgrest(*responses)
    return SupabaseRepository("https://example.supabase.co", KEY, transport=httpx.MockTransport(fake)), fake


def body_of(request):
    return json.loads(request.content) if request.content else {}


def test_requests_carry_user_token_not_service_key():
    repo, fake = make_repo((200, [dict(ROW)]))
    repo.list_reports(USER)
    req = fake.requests[0]
    assert req.headers["apikey"] == KEY
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert req.url.path == "/rest/v1/hazard_reports"
    # 사용자·사업장 필터를 앱이 걸지 않는다 → 범위는 RLS 가 정한다
    assert "reported_by" not in req.url.params and "organization_id" not in req.url.params


def test_list_flattens_reporter_name():
    repo, _ = make_repo((200, [dict(ROW)]))
    assert repo.list_reports(USER)[0]["reporter_name"] == "작업자"


def test_create_sends_only_area_and_hazard():
    repo, fake = make_repo((201, [dict(ROW)]))
    repo.create_report(USER, "  A동  ", " 위험 ")
    assert body_of(fake.requests[0]) == {"area": "A동", "hazard": "위험"}
    assert fake.requests[0].headers["prefer"] == "return=representation"


def test_update_filters_by_id_and_sends_cleaned_values():
    repo, fake = make_repo((200, [dict(ROW)]))
    repo.update_report(USER, RID, {"action": "  조치 ", "due_date": "", "status": "in_progress"})
    req = fake.requests[0]
    assert req.method == "PATCH" and req.url.params["id"] == f"eq.{RID}"
    assert body_of(req) == {"action": "조치", "due_date": None, "status": "in_progress"}


def test_update_zero_rows_is_not_found():
    repo, _ = make_repo((200, []))
    with pytest.raises(domain.NotFound):
        repo.update_report(USER, RID, {"status": "in_progress"})


def test_update_rejects_non_updatable_fields_without_request():
    repo, fake = make_repo()
    with pytest.raises(domain.ValidationError):
        repo.update_report(USER, RID, {"reported_by": str(uuid.uuid4())})
    assert fake.requests == []


def test_malformed_id_is_not_found_without_request():
    repo, fake = make_repo()
    with pytest.raises(domain.NotFound):
        repo.get_report(USER, "1 or 1=1")
    assert fake.requests == []


@pytest.mark.parametrize("status,body,error", [
    (403, {"code": "42501", "message": "permission denied for table hazard_reports"}, domain.PermissionDenied),
    (400, {"code": "23514", "message": "violates check constraint"}, domain.ValidationError),
    (400, {"code": "P0001", "message": "report limit reached", "hint": "report_limit"}, domain.TooManyRequests),
    (401, {"code": "PGRST301", "message": "JWT expired"}, domain.Unauthorized),
    (500, {"code": "XX000", "message": "internal"}, domain.StorageUnavailable),
])
def test_db_errors_are_mapped(status, body, error):
    repo, _ = make_repo((status, body))
    with pytest.raises(error):
        repo.create_report(USER, "A", "B")


def test_db_error_details_are_not_leaked():
    repo, _ = make_repo((500, {"code": "XX000", "message": "select * from secret_table"}))
    with pytest.raises(domain.StorageUnavailable) as exc:
        repo.list_reports(USER)
    assert "secret_table" not in str(exc.value)


def test_get_profile_queries_own_row():
    repo, fake = make_repo((200, [{"role": "worker", "organization_id": "o", "display_name": "n"}]))
    assert repo.get_profile(USER)["role"] == "worker"
    assert fake.requests[0].url.params["user_id"] == f"eq.{USER.id}"


def test_reset_demo_calls_rpc():
    repo, fake = make_repo((200, 4))
    assert repo.reset_demo(USER) == 4
    assert fake.requests[0].url.path == "/rest/v1/rpc/reset_demo_data"
