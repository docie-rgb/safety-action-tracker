"""RLS·권한 실제 검증 스크립트 — 데모 계정의 "일반 사용자 토큰"으로 실제 Supabase 와 앱 API 를 호출한다.

실행 (프로젝트 폴더에서):
    .venv/Scripts/python -m scripts.rls_check
    RLS_CHECK_API_BASE=https://<앱>.onrender.com .venv/Scripts/python -m scripts.rls_check   # 배포본 검증

필요한 .env 값: SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, DEMO_WORKER_*, DEMO_MANAGER_*
선택: RLS_TEST_WORKER2_EMAIL/PASSWORD (작업자끼리 격리 확인)

[DB 직접] 백엔드를 거치지 않고 Supabase REST(/rest/v1)에 각 사용자 토큰으로 요청한다.
          → Python 코드가 아니라 DB 의 RLS·컬럼 권한이 막는지 확인한다.
[앱 API]  실행 중인 서버(RLS_CHECK_API_BASE, 기본 http://127.0.0.1:8000)에 같은 공격을 보낸다. 서버가 없으면 건너뛴다.
관리자(secret/service_role) 키는 사용하지 않는다. 출력에 토큰·비밀번호를 표시하지 않는다.
검증용으로 만든 행은 마지막에 삭제한다. 결과는 docs/rls_check_result.md 에 저장한다.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import httpx

from backend import config
from backend.supabase_auth import SupabaseAuth

API_BASE = os.getenv("RLS_CHECK_API_BASE", "http://127.0.0.1:8000").rstrip("/")
RESULT_FILE = Path(__file__).resolve().parent.parent / "docs" / "rls_check_result.md"
OTHER_ORG = "00000000-0000-4000-8000-0000000000ff"
TAG = "[RLS검증]"

results: list[tuple[str, str, bool, str]] = []


def check(group: str, name: str, ok: bool, evidence: str) -> None:
    results.append((group, name, ok, evidence))
    print(f"[{'PASS' if ok else 'FAIL'}] {group} | {name} — {evidence}")


class Rest:
    """한 사용자의 토큰으로 Supabase REST 를 호출한다 (token=None 이면 비로그인)."""

    def __init__(self, token: str | None):
        self.headers = {"apikey": config.SUPABASE_PUBLISHABLE_KEY, "Prefer": "return=representation"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(base_url=f"{config.SUPABASE_URL}/rest/v1", timeout=15.0)

    def call(self, method: str, path: str, params=None, json=None):
        r = self.http.request(method, path, params=params, json=json, headers=self.headers)
        try:
            body = r.json() if r.content else []
        except ValueError:
            body = None
        return r.status_code, body


def code_of(body) -> str | None:
    return body.get("code") if isinstance(body, dict) else None


def desc(status, body) -> str:
    if isinstance(body, list):
        return f"HTTP {status}, {len(body)}건"
    return f"HTTP {status}, code={code_of(body)}"


def denied(status, body) -> bool:
    return status in (401, 403) or code_of(body) in ("42501", "42P01")


def db_checks(worker: Rest, worker_id: str, manager: Rest, manager_id: str, worker2: Rest | None) -> str | None:
    """DB 직접 검증. 관리자가 만든 신고 ID 를 돌려준다 (앱 API 의 타인 신고 조회 검증용)."""
    G = "DB 직접"

    s, b = Rest(None).call("GET", "/hazard_reports", params={"select": "id"})
    check(G, "비로그인 조회 차단", denied(s, b) or b == [], desc(s, b))

    base = {"area": f"{TAG} 구역", "hazard": f"{TAG} 위험요인"}
    for label, extra in [
        ("완료 상태 지정", {"status": "completed"}),
        ("조치 내용 지정", {"action": "임의 조치"}),
        ("조치기한 지정", {"due_date": "2030-01-01"}),
        ("타인 ID 로 신고", {"reported_by": manager_id}),
        ("다른 사업장 ID 위조", {"organization_id": OTHER_ORG}),
    ]:
        s, b = worker.call("POST", "/hazard_reports", json={**base, **extra})
        check(G, f"작업자 생성 시 {label} 거부", denied(s, b), desc(s, b))

    s, b = worker.call("POST", "/hazard_reports", json=base)
    ok = s == 201 and isinstance(b, list) and b[0]["status"] == "received" and b[0]["reported_by"] == worker_id
    check(G, "작업자 정상 신고 (본인 ID·접수 상태 자동)", ok, desc(s, b))
    w_report = b[0]["id"] if ok else None

    s, b = manager.call("POST", "/hazard_reports", json={"area": f"{TAG} 관리자 구역", "hazard": f"{TAG} 관리자 신고"})
    m_report = b[0]["id"] if s == 201 and isinstance(b, list) else None

    s, b = worker.call("GET", "/hazard_reports", params={"select": "id,reported_by"})
    check(G, "작업자 목록은 본인 신고만", isinstance(b, list) and all(r["reported_by"] == worker_id for r in b), desc(s, b))

    if m_report:
        s, b = worker.call("GET", "/hazard_reports", params={"select": "id", "id": f"eq.{m_report}"})
        check(G, "작업자가 타인 신고 ID 직접 조회 → 0건", b == [], desc(s, b))

    if w_report:
        s, b = worker.call("PATCH", "/hazard_reports", params={"id": f"eq.{w_report}"}, json={"status": "completed", "action": "x"})
        check(G, "작업자 상태·조치 수정 차단", denied(s, b) or b == [], desc(s, b))
        s, b = worker.call("DELETE", "/hazard_reports", params={"id": f"eq.{w_report}"})
        check(G, "작업자 삭제 차단 (0건)", denied(s, b) or b == [], desc(s, b))
        s, b = manager.call("GET", "/hazard_reports", params={"select": "status,action", "id": f"eq.{w_report}"})
        check(G, "작업자 시도 후에도 원래 상태 유지", isinstance(b, list) and b and b[0]["status"] == "received" and b[0]["action"] is None, desc(s, b))

    s, b = worker.call("PATCH", "/profiles", params={"user_id": f"eq.{worker_id}"}, json={"role": "manager"})
    check(G, "작업자 자신의 역할 변경 차단", denied(s, b) or b == [], desc(s, b))
    s, b = worker.call("GET", "/profiles", params={"select": "role", "user_id": f"eq.{worker_id}"})
    check(G, "작업자 역할은 여전히 worker", isinstance(b, list) and b and b[0]["role"] == "worker", desc(s, b))
    s, b = worker.call("POST", "/profiles", json={"user_id": worker_id, "organization_id": OTHER_ORG, "role": "manager", "display_name": "x"})
    check(G, "작업자 프로필 생성 차단", denied(s, b), desc(s, b))
    s, b = worker.call("GET", "/profiles", params={"select": "user_id"})
    check(G, "작업자는 타인 프로필 조회 불가", isinstance(b, list) and all(r["user_id"] == worker_id for r in b), desc(s, b))
    s, b = worker.call("POST", "/rpc/reset_demo_data", json={})
    check(G, "작업자 데모 초기화 RPC 차단", denied(s, b), desc(s, b))

    if worker2 and w_report:
        s, b = worker2.call("GET", "/hazard_reports", params={"select": "id", "id": f"eq.{w_report}"})
        check(G, "다른 작업자는 내 신고를 볼 수 없음", b == [], desc(s, b))

    if w_report:
        s, b = manager.call("GET", "/hazard_reports", params={"select": "id", "id": f"eq.{w_report}"})
        check(G, "관리자는 작업자 신고 조회", isinstance(b, list) and len(b) == 1, desc(s, b))
        s, b = manager.call("PATCH", "/hazard_reports", params={"id": f"eq.{w_report}"}, json={"status": "completed"})
        check(G, "조치 내용 없이 완료 처리 거부 (CHECK)", code_of(b) == "23514", desc(s, b))
        s, b = manager.call("PATCH", "/hazard_reports", params={"id": f"eq.{w_report}"},
                            json={"action": f"{TAG} 조치", "due_date": "2030-01-31", "status": "in_progress"})
        check(G, "관리자 개선조치·기한·상태 수정", isinstance(b, list) and len(b) == 1 and b[0]["status"] == "in_progress", desc(s, b))
        s, b = manager.call("PATCH", "/hazard_reports", params={"id": f"eq.{w_report}"}, json={"status": "completed"})
        check(G, "관리자 완료 처리 → 완료일 자동 기록", isinstance(b, list) and len(b) == 1 and b[0]["completed_at"], desc(s, b))
        s, b = manager.call("PATCH", "/hazard_reports", params={"id": f"eq.{w_report}"}, json={"reported_by": manager_id})
        check(G, "관리자도 신고자 변경 불가 (컬럼 권한)", denied(s, b), desc(s, b))
        s, b = manager.call("PATCH", "/hazard_reports", params={"id": f"eq.{w_report}"}, json={"organization_id": OTHER_ORG})
        check(G, "관리자도 사업장 이동 불가", denied(s, b), desc(s, b))
        s, b = worker.call("GET", "/hazard_reports", params={"select": "status,action", "id": f"eq.{w_report}"})
        check(G, "관리자 변경이 작업자 조회에 반영", isinstance(b, list) and b and b[0]["status"] == "completed", desc(s, b))

    s, b = manager.call("PATCH", "/profiles", params={"user_id": f"eq.{manager_id}"}, json={"role": "worker"})
    check(G, "관리자도 역할 변경 불가", denied(s, b) or b == [], desc(s, b))
    return m_report


def api_checks(m_report_id: str | None) -> None:
    G = "앱 API"
    try:
        httpx.get(f"{API_BASE}/api/health", timeout=60.0).raise_for_status()
    except httpx.HTTPError:
        print(f"[SKIP] 앱 API 검증 — {API_BASE} 에 서버가 없습니다.")
        return
    anon = httpx.Client(base_url=API_BASE, timeout=30.0)
    s = anon.get("/api/reports").status_code
    check(G, "비로그인 /api/reports 401", s == 401, f"HTTP {s}")

    w = httpx.Client(base_url=API_BASE, timeout=30.0)
    r = w.post("/api/auth/demo", json={"role": "worker"})
    check(G, "작업자 데모 로그인", r.status_code == 200 and r.json()["user"]["role"] == "worker", f"HTTP {r.status_code}")
    r = w.post("/api/reports", json={"area": f"{TAG} API", "hazard": f"{TAG} API", "status": "completed"})
    check(G, "작업자 생성 시 status 지정 → 422", r.status_code == 422, f"HTTP {r.status_code}")
    r = w.post("/api/reports", json={"area": f"{TAG} API", "hazard": f"{TAG} API"})
    own = r.json().get("id") if r.status_code == 201 else None
    check(G, "작업자 신고 등록", own is not None, f"HTTP {r.status_code}")
    if m_report_id:
        r = w.get(f"/api/reports/{m_report_id}")
        check(G, "작업자가 타인 신고 ID 조회 → 404", r.status_code == 404, f"HTTP {r.status_code}")
    if own:
        r = w.patch(f"/api/reports/{own}", json={"status": "completed", "action": "x"})
        check(G, "작업자 PATCH → 403", r.status_code == 403, f"HTTP {r.status_code}")
        r = w.delete(f"/api/reports/{own}")
        check(G, "작업자 DELETE → 403", r.status_code == 403, f"HTTP {r.status_code}")

    m = httpx.Client(base_url=API_BASE, timeout=30.0)
    r = m.post("/api/auth/demo", json={"role": "manager"})
    check(G, "관리자 데모 로그인", r.status_code == 200 and r.json()["user"]["role"] == "manager", f"HTTP {r.status_code}")
    if own:
        r = m.patch(f"/api/reports/{own}", json={"action": f"{TAG} API 조치", "status": "in_progress"})
        check(G, "관리자 PATCH", r.status_code == 200 and r.json()["status"] == "in_progress", f"HTTP {r.status_code}")
        r = w.get(f"/api/reports/{own}")
        check(G, "작업자 화면 데이터에 반영", r.status_code == 200 and r.json()["status"] == "in_progress", f"HTTP {r.status_code}")
        r = m.delete(f"/api/reports/{own}")
        check(G, "관리자 DELETE", r.status_code == 204, f"HTTP {r.status_code}")
    for c in (w, m):
        c.post("/api/auth/logout")


def write_report() -> None:
    passed = sum(1 for r in results if r[2])
    lines = [
        "# RLS·권한 실제 검증 결과",
        "",
        f"- 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 앱 API 대상: `{API_BASE}`",
        f"- 결과: {passed} / {len(results)} 통과",
        "- 방식: 데모 계정의 일반 사용자 토큰으로 Supabase REST 직접 호출 + 앱 API 호출 (service_role 키 미사용)",
        "",
        "| 구분 | 항목 | 결과 | 근거 |",
        "|---|---|---|---|",
    ]
    lines += [f"| {g} | {n} | {'PASS' if ok else 'FAIL'} | {e} |" for g, n, ok, e in results]
    RESULT_FILE.parent.mkdir(exist_ok=True)
    RESULT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔(cp949)에서도 출력되도록
    if not config.SUPABASE_URL or not config.SUPABASE_PUBLISHABLE_KEY:
        sys.exit(".env 에 SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY 가 없습니다.")
    if config.SUPABASE_PUBLISHABLE_KEY.startswith("sb_secret_"):
        sys.exit("SUPABASE_PUBLISHABLE_KEY 에 secret 키가 들어 있습니다. publishable 키로 바꾸세요.")
    auth = SupabaseAuth(config.SUPABASE_URL, config.SUPABASE_PUBLISHABLE_KEY)
    sw = auth.sign_in(*config.DEMO_ACCOUNTS["worker"])
    sm = auth.sign_in(*config.DEMO_ACCOUNTS["manager"])
    worker2 = None
    if os.getenv("RLS_TEST_WORKER2_EMAIL") and os.getenv("RLS_TEST_WORKER2_PASSWORD"):
        worker2 = Rest(auth.sign_in(os.environ["RLS_TEST_WORKER2_EMAIL"], os.environ["RLS_TEST_WORKER2_PASSWORD"]).access_token)

    worker, manager = Rest(sw.access_token), Rest(sm.access_token)
    try:
        m_report = db_checks(worker, sw.user_id, manager, sm.user_id, worker2)
        api_checks(m_report)
    finally:
        # 검증용 행 정리 (관리자 권한으로 태그가 붙은 행 삭제)
        manager.call("DELETE", "/hazard_reports", params={"area": f"like.{TAG}*"})
    write_report()
    failed = [r for r in results if not r[2]]
    print(f"\n{len(results) - len(failed)} / {len(results)} 통과. 결과 파일: {RESULT_FILE}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
