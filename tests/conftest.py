"""API 테스트용 가짜 인증 서버(FakeAuth)와, DB의 RLS 규칙을 흉내 낸 메모리 저장소(FakeRepo).

이 테스트가 증명하는 것:
  - FastAPI 계층의 인증·역할 검사, 입력 검증, 쿠키·CSRF 처리
이 테스트가 증명하지 못하는 것:
  - 실제 PostgreSQL 의 RLS·컬럼 권한 → scripts/rls_check.py 로 실제 Supabase 에서 검증한다.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend import config, domain, ratelimit
from backend.api import auth as auth_api
from backend.api import deps
from backend.api import reports as reports_api
from backend.domain import CurrentUser
from backend.main import app
from backend.supabase_auth import Session

ORG = "00000000-0000-4000-8000-000000000001"
OTHER_ORG = "00000000-0000-4000-8000-000000000002"

ACCOUNTS = {
    # email: (password, user_id, role, org, display_name)
    "worker@example.com": ("worker-pw", "11111111-1111-4111-8111-111111111111", "worker", ORG, "작업자1"),
    "worker2@example.com": ("worker2-pw", "22222222-2222-4222-8222-222222222222", "worker", ORG, "작업자2"),
    "manager@example.com": ("manager-pw", "33333333-3333-4333-8333-333333333333", "manager", ORG, "관리자"),
    "other-manager@example.com": ("other-pw", "44444444-4444-4444-8444-444444444444", "manager", OTHER_ORG, "타사 관리자"),
    "norole@example.com": ("norole-pw", "55555555-5555-4555-8555-555555555555", None, None, None),
}


class FakeAuth:
    def __init__(self):
        self.tokens: dict[str, str] = {}  # access token → email
        self.refresh_tokens: dict[str, str] = {}
        self.signed_out: list[str] = []
        self.counter = 0

    def _new_session(self, email):
        self.counter += 1
        access, refresh = f"access-{self.counter}", f"refresh-{self.counter}"
        self.tokens[access] = email
        self.refresh_tokens[refresh] = email
        return Session(user_id=ACCOUNTS[email][1], email=email, access_token=access, refresh_token=refresh, expires_in=3600)

    def sign_in(self, email, password):
        if email not in ACCOUNTS or ACCOUNTS[email][0] != password:
            raise domain.Unauthorized("이메일 또는 비밀번호가 올바르지 않습니다.")
        return self._new_session(email)

    def refresh(self, refresh_token):
        email = self.refresh_tokens.pop(refresh_token, None)
        if email is None:
            raise domain.Unauthorized("로그인이 만료되었습니다. 다시 로그인하세요.")
        return self._new_session(email)

    def get_user(self, access_token):
        email = self.tokens.get(access_token)
        if email is None:
            raise domain.Unauthorized("로그인이 만료되었습니다. 다시 로그인하세요.")
        return CurrentUser(id=ACCOUNTS[email][1], email=email, access_token=access_token)

    def sign_out(self, access_token):
        self.signed_out.append(access_token)
        self.tokens.pop(access_token, None)


class FakeRepo:
    """supabase/schema.sql 의 RLS 규칙을 같은 의미로 흉내 낸다. 역할은 '토큰의 사용자 ID'로만 찾는다."""

    def __init__(self, auth: FakeAuth):
        self.auth = auth
        self.reports: dict[str, dict] = {}

    def _profile_of(self, user: CurrentUser):
        email = self.auth.tokens.get(user.access_token)
        if email is None:
            raise domain.Unauthorized()
        _, uid, role, org, name = ACCOUNTS[email]
        return uid, role, org, name

    def get_profile(self, user):
        uid, role, org, name = self._profile_of(user)
        return None if role is None else {"role": role, "organization_id": org, "display_name": name}

    def _visible(self, user, r):
        uid, role, org, _ = self._profile_of(user)
        return r["organization_id"] == org and (r["reported_by"] == uid or role == "manager")

    def _out(self, r):
        name = next(a[4] for a in ACCOUNTS.values() if a[1] == r["reported_by"])
        return {**r, "reporter_name": name}

    def list_reports(self, user, status=None):
        rows = [r for r in self.reports.values() if self._visible(user, r) and (status is None or r["status"] == status)]
        return [self._out(r) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]

    def get_report(self, user, report_id):
        r = self.reports.get(report_id)
        if not r or not self._visible(user, r):
            raise domain.NotFound()
        return self._out(r)

    def create_report(self, user, area, hazard):
        uid, role, org, _ = self._profile_of(user)
        now = datetime.now(timezone.utc).isoformat()
        r = {
            "id": str(uuid.uuid4()),
            "organization_id": org,
            "reported_by": uid,
            "area": domain.clean_text(area, "작업구역", domain.AREA_MAX),
            "hazard": domain.clean_text(hazard, "위험요인 설명", domain.HAZARD_MAX),
            "action": None,
            "status": "received",
            "due_date": None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self.reports[r["id"]] = r
        return self._out(r)

    def _manageable(self, user, report_id):
        uid, role, org, _ = self._profile_of(user)
        r = self.reports.get(report_id)
        if not r or r["organization_id"] != org or role != "manager":
            raise domain.NotFound()  # RLS: 0건
        return r

    def update_report(self, user, report_id, changes):
        r = self._manageable(user, report_id)
        new = dict(r)
        if "action" in changes:
            new["action"] = domain.clean_optional_text(changes["action"], "개선조치 내용", domain.ACTION_MAX)
        if "status" in changes:
            new["status"] = domain.clean_status(changes["status"])
        if "due_date" in changes:
            new["due_date"] = domain.clean_due_date(changes["due_date"])
        if new["status"] == "completed" and not new["action"]:
            raise domain.ValidationError("저장 규칙에 맞지 않습니다. 완료 처리에는 개선조치 내용이 필요합니다.")
        if new["status"] == "completed" and r["status"] != "completed":
            new["completed_at"] = datetime.now(timezone.utc).isoformat()
        elif new["status"] != "completed":
            new["completed_at"] = None
        self.reports[report_id] = new
        return self._out(new)

    def delete_report(self, user, report_id):
        self._manageable(user, report_id)
        del self.reports[report_id]

    def reset_demo(self, user):
        uid, role, org, _ = self._profile_of(user)
        if role != "manager":
            raise domain.PermissionDenied()
        for rid in [k for k, r in self.reports.items() if r["organization_id"] == org]:
            del self.reports[rid]
        return 0


@pytest.fixture
def fake_auth():
    return FakeAuth()


@pytest.fixture
def fake_repo(fake_auth):
    return FakeRepo(fake_auth)


@pytest.fixture(autouse=True)
def wire(monkeypatch, fake_auth, fake_repo):
    """실제 Supabase 에 접속하지 않도록 인증·저장소를 가짜로 바꾸고, 요청 제한 카운트를 비운다."""
    for module in (deps, auth_api):
        monkeypatch.setattr(module, "get_auth", lambda: fake_auth)
    for module in (deps, reports_api):
        monkeypatch.setattr(module, "get_repo", lambda: fake_repo)
    monkeypatch.setattr(config, "DEMO_ACCOUNTS", {
        "worker": ("worker@example.com", "worker-pw"),
        "manager": ("manager@example.com", "manager-pw"),
    })
    ratelimit.login_limiter.reset()
    ratelimit.report_limiter.reset()
    yield


def make_client():
    return TestClient(app, base_url="http://testserver")


def login(email: str) -> TestClient:
    client = make_client()
    res = client.post("/api/auth/login", json={"email": email, "password": ACCOUNTS[email][0]})
    assert res.status_code == 200, res.text
    return client


@pytest.fixture
def worker():
    return login("worker@example.com")


@pytest.fixture
def worker2():
    return login("worker2@example.com")


@pytest.fixture
def manager():
    return login("manager@example.com")
