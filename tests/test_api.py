"""역할별 기능·권한 API 테스트 (FakeAuth + RLS 를 흉내 낸 FakeRepo)."""

import pytest

from tests.conftest import make_client

NEW = {"area": "A동 계단", "hazard": "난간 볼트 풀림"}


def create(client, body=NEW):
    res = client.post("/api/reports", json=body)
    assert res.status_code == 201, res.text
    return res.json()


# ---------- 인증 ----------


def test_health_and_index_are_public():
    client = make_client()
    assert client.get("/api/health").json() == {"status": "ok"}
    res = client.get("/")
    assert res.status_code == 200 and "Safety Action Tracker" in res.text


def test_me_without_login_is_unauthenticated():
    assert make_client().get("/api/me").json() == {"authenticated": False, "user": None}


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/reports"),
    ("POST", "/api/reports"),
    ("GET", "/api/reports/00000000-0000-4000-8000-000000000099"),
    ("PATCH", "/api/reports/00000000-0000-4000-8000-000000000099"),
    ("DELETE", "/api/reports/00000000-0000-4000-8000-000000000099"),
    ("POST", "/api/demo/reset"),
])
def test_data_api_requires_login(method, path):
    res = make_client().request(method, path, json={} if method in ("POST", "PATCH") else None)
    assert res.status_code == 401


def test_demo_login_sets_httponly_cookies_and_returns_db_role():
    client = make_client()
    res = client.post("/api/auth/demo", json={"role": "manager"})
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["role"] == "manager"
    assert "access" not in res.text and "refresh-" not in res.text  # 토큰은 본문에 없다
    cookies = res.headers.get_list("set-cookie")
    assert any(c.startswith("sat_access=") and "HttpOnly" in c for c in cookies)
    assert any(c.startswith("sat_refresh=") and "HttpOnly" in c for c in cookies)
    assert client.get("/api/me").json()["user"]["role"] == "manager"


def test_demo_login_rejects_unknown_role_and_extra_fields():
    client = make_client()
    assert client.post("/api/auth/demo", json={"role": "admin"}).status_code == 422
    assert client.post("/api/auth/demo", json={"role": "worker", "password": "x"}).status_code == 422


def test_login_ignores_client_supplied_role():
    """role 을 함께 보내도 권한이 올라가지 않는다 (422 거부)."""
    client = make_client()
    res = client.post("/api/auth/login", json={"email": "worker@example.com", "password": "worker-pw", "role": "manager"})
    assert res.status_code == 422


def test_role_comes_from_db_not_from_demo_button(monkeypatch):
    """데모 버튼 값이 manager 여도, 그 버튼에 연결된 계정의 DB 역할이 worker 면 worker 다."""
    from backend import config

    monkeypatch.setitem(config.DEMO_ACCOUNTS, "manager", ("worker@example.com", "worker-pw"))
    client = make_client()
    assert client.post("/api/auth/demo", json={"role": "manager"}).json()["user"]["role"] == "worker"
    assert client.patch("/api/reports/00000000-0000-4000-8000-000000000099", json={"status": "completed"}).status_code == 403


def test_wrong_password_is_401():
    res = make_client().post("/api/auth/login", json={"email": "worker@example.com", "password": "nope"})
    assert res.status_code == 401


def test_account_without_profile_gets_no_session(fake_auth):
    client = make_client()
    res = client.post("/api/auth/login", json={"email": "norole@example.com", "password": "norole-pw"})
    assert res.status_code == 403
    assert not any(c.startswith("sat_") for c in res.headers.get_list("set-cookie"))
    assert fake_auth.signed_out  # 바로 세션 종료


def test_logout_clears_cookies(worker, fake_auth):
    res = worker.post("/api/auth/logout")
    assert res.status_code == 204
    assert fake_auth.signed_out
    assert worker.get("/api/me").json()["authenticated"] is False


def test_me_refreshes_expired_access_token(worker, fake_auth):
    fake_auth.tokens.clear()  # 액세스 토큰 만료
    body = worker.get("/api/me").json()
    assert body["authenticated"] is True and body["user"]["role"] == "worker"


# ---------- 작업자 ----------


def test_worker_creates_report_with_initial_state(worker):
    r = create(worker)
    assert r["status"] == "received" and r["action"] is None and r["due_date"] is None
    assert r["reported_by"] == "11111111-1111-4111-8111-111111111111"
    assert [x["id"] for x in worker.get("/api/reports").json()] == [r["id"]]


@pytest.mark.parametrize("extra", [
    {"status": "completed"},
    {"action": "조치 완료"},
    {"due_date": "2030-01-01"},
    {"reported_by": "22222222-2222-4222-8222-222222222222"},
    {"organization_id": "00000000-0000-4000-8000-000000000002"},
    {"role": "manager"},
])
def test_worker_cannot_set_manager_fields_on_create(worker, extra):
    res = worker.post("/api/reports", json={**NEW, **extra})
    assert res.status_code == 422
    assert worker.get("/api/reports").json() == []


@pytest.mark.parametrize("body", [
    {"area": "  ", "hazard": "x"},
    {"area": "x", "hazard": ""},
    {"area": "x" * 101, "hazard": "x"},
    {"area": "x", "hazard": "x" * 1001},
    {"area": "x"},
])
def test_create_validates_input(worker, body):
    assert worker.post("/api/reports", json=body).status_code in (400, 422)


def test_worker_sees_only_own_reports(worker, worker2):
    mine = create(worker)
    theirs = create(worker2, {"area": "B동", "hazard": "누유"})
    assert [r["id"] for r in worker.get("/api/reports").json()] == [mine["id"]]
    # 타인 신고 ID 로 직접 조회 → 차단 (존재 여부도 알려 주지 않는 404)
    assert worker.get(f"/api/reports/{theirs['id']}").status_code == 404


def test_worker_cannot_patch_or_delete(worker):
    r = create(worker)
    assert worker.patch(f"/api/reports/{r['id']}", json={"status": "completed", "action": "x"}).status_code == 403
    assert worker.patch(f"/api/reports/{r['id']}", json={"action": "x"}).status_code == 403
    assert worker.delete(f"/api/reports/{r['id']}").status_code == 403
    assert worker.post("/api/demo/reset").status_code == 403
    assert worker.get(f"/api/reports/{r['id']}").json()["status"] == "received"


def test_report_rate_limit(worker):
    for _ in range(20):
        create(worker)
    assert worker.post("/api/reports", json=NEW).status_code == 429


# ---------- 관리자 ----------


def test_manager_sees_all_reports_in_org(worker, worker2, manager):
    a = create(worker)
    b = create(worker2, {"area": "B동", "hazard": "누유"})
    rows = manager.get("/api/reports").json()
    assert {r["id"] for r in rows} == {a["id"], b["id"]}
    assert {r["reporter_name"] for r in rows} == {"작업자1", "작업자2"}
    assert manager.get(f"/api/reports/{a['id']}").status_code == 200


def test_manager_of_other_org_cannot_see_or_change(worker):
    r = create(worker)
    other = make_client()
    other.post("/api/auth/login", json={"email": "other-manager@example.com", "password": "other-pw"})
    assert other.get("/api/reports").json() == []
    assert other.get(f"/api/reports/{r['id']}").status_code == 404
    assert other.patch(f"/api/reports/{r['id']}", json={"status": "in_progress"}).status_code == 404
    assert other.delete(f"/api/reports/{r['id']}").status_code == 404


def test_full_flow_manager_action_visible_to_worker(worker, manager):
    r = create(worker)
    res = manager.patch(f"/api/reports/{r['id']}", json={"action": "볼트 재체결", "due_date": "2030-01-31", "status": "in_progress"})
    assert res.status_code == 200
    assert res.json()["status"] == "in_progress"

    mine = worker.get(f"/api/reports/{r['id']}").json()
    assert (mine["action"], mine["due_date"], mine["status"]) == ("볼트 재체결", "2030-01-31", "in_progress")

    done = manager.patch(f"/api/reports/{r['id']}", json={"status": "completed"}).json()
    assert done["status"] == "completed" and done["completed_at"]
    assert worker.get("/api/reports").json()[0]["status"] == "completed"


def test_complete_requires_action(worker, manager):
    r = create(worker)
    assert manager.patch(f"/api/reports/{r['id']}", json={"status": "completed"}).status_code == 400


@pytest.mark.parametrize("body", [
    {"status": "done"},
    {"status": None},
    {"due_date": "2030-02-30"},
    {"due_date": "31/01/2030"},
    {"area": "변경"},
    {"hazard": "변경"},
    {"reported_by": "22222222-2222-4222-8222-222222222222"},
    {},
])
def test_patch_validates_input(worker, manager, body):
    r = create(worker)
    assert manager.patch(f"/api/reports/{r['id']}", json=body).status_code in (400, 422)


def test_manager_deletes_report(worker, manager):
    r = create(worker)
    assert manager.delete(f"/api/reports/{r['id']}").status_code == 204
    assert manager.get(f"/api/reports/{r['id']}").status_code == 404
    assert worker.get("/api/reports").json() == []


def test_unknown_or_malformed_id_is_404(manager):
    assert manager.get("/api/reports/00000000-0000-4000-8000-000000000099").status_code == 404
    assert manager.delete("/api/reports/00000000-0000-4000-8000-000000000099").status_code == 404


def test_status_filter(worker, manager):
    a = create(worker)
    create(worker, {"area": "C동", "hazard": "조명 불량"})
    manager.patch(f"/api/reports/{a['id']}", json={"status": "in_progress"})
    rows = manager.get("/api/reports?status=in_progress").json()
    assert [r["id"] for r in rows] == [a["id"]]
    assert manager.get("/api/reports?status=bogus").status_code == 422


# ---------- CSRF ----------


def test_foreign_origin_is_rejected(worker):
    res = worker.post("/api/reports", json=NEW, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403


def test_same_origin_is_allowed(worker):
    res = worker.post("/api/reports", json=NEW, headers={"Origin": "http://testserver"})
    assert res.status_code == 201


def test_non_json_body_is_rejected(worker):
    res = worker.post("/api/reports", content="area=x&hazard=y", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert res.status_code == 415


def test_security_headers():
    res = make_client().get("/")
    assert "frame-ancestors 'none'" in res.headers["content-security-policy"]
    assert res.headers["x-content-type-options"] == "nosniff"
