# RLS·권한 실제 검증 결과

- 실행 시각: 2026-11-03 15:25:19
- 앱 API 대상: `http://127.0.0.1:8000`
- 결과: 36 / 36 통과
- 방식: 데모 계정의 일반 사용자 토큰으로 Supabase REST 직접 호출 + 앱 API 호출 (service_role 키 미사용)

| 구분 | 항목 | 결과 | 근거 |
|---|---|---|---|
| DB 직접 | 비로그인 조회 차단 | PASS | HTTP 401, code=42501 |
| DB 직접 | 작업자 생성 시 완료 상태 지정 거부 | PASS | HTTP 403, code=42501 |
| DB 직접 | 작업자 생성 시 조치 내용 지정 거부 | PASS | HTTP 403, code=42501 |
| DB 직접 | 작업자 생성 시 조치기한 지정 거부 | PASS | HTTP 403, code=42501 |
| DB 직접 | 작업자 생성 시 타인 ID 로 신고 거부 | PASS | HTTP 403, code=42501 |
| DB 직접 | 작업자 생성 시 다른 사업장 ID 위조 거부 | PASS | HTTP 403, code=42501 |
| DB 직접 | 작업자 정상 신고 (본인 ID·접수 상태 자동) | PASS | HTTP 201, 1건 |
| DB 직접 | 작업자 목록은 본인 신고만 | PASS | HTTP 200, 5건 |
| DB 직접 | 작업자가 타인 신고 ID 직접 조회 → 0건 | PASS | HTTP 200, 0건 |
| DB 직접 | 작업자 상태·조치 수정 차단 | PASS | HTTP 200, 0건 |
| DB 직접 | 작업자 삭제 차단 (0건) | PASS | HTTP 200, 0건 |
| DB 직접 | 작업자 시도 후에도 원래 상태 유지 | PASS | HTTP 200, 1건 |
| DB 직접 | 작업자 자신의 역할 변경 차단 | PASS | HTTP 403, code=42501 |
| DB 직접 | 작업자 역할은 여전히 worker | PASS | HTTP 200, 1건 |
| DB 직접 | 작업자 프로필 생성 차단 | PASS | HTTP 403, code=42501 |
| DB 직접 | 작업자는 타인 프로필 조회 불가 | PASS | HTTP 200, 1건 |
| DB 직접 | 작업자 데모 초기화 RPC 차단 | PASS | HTTP 403, code=42501 |
| DB 직접 | 관리자는 작업자 신고 조회 | PASS | HTTP 200, 1건 |
| DB 직접 | 조치 내용 없이 완료 처리 거부 (CHECK) | PASS | HTTP 400, code=23514 |
| DB 직접 | 관리자 개선조치·기한·상태 수정 | PASS | HTTP 200, 1건 |
| DB 직접 | 관리자 완료 처리 → 완료일 자동 기록 | PASS | HTTP 200, 1건 |
| DB 직접 | 관리자도 신고자 변경 불가 (컬럼 권한) | PASS | HTTP 403, code=42501 |
| DB 직접 | 관리자도 사업장 이동 불가 | PASS | HTTP 403, code=42501 |
| DB 직접 | 관리자 변경이 작업자 조회에 반영 | PASS | HTTP 200, 1건 |
| DB 직접 | 관리자도 역할 변경 불가 | PASS | HTTP 403, code=42501 |
| 앱 API | 비로그인 /api/reports 401 | PASS | HTTP 401 |
| 앱 API | 작업자 데모 로그인 | PASS | HTTP 200 |
| 앱 API | 작업자 생성 시 status 지정 → 422 | PASS | HTTP 422 |
| 앱 API | 작업자 신고 등록 | PASS | HTTP 201 |
| 앱 API | 작업자가 타인 신고 ID 조회 → 404 | PASS | HTTP 404 |
| 앱 API | 작업자 PATCH → 403 | PASS | HTTP 403 |
| 앱 API | 작업자 DELETE → 403 | PASS | HTTP 403 |
| 앱 API | 관리자 데모 로그인 | PASS | HTTP 200 |
| 앱 API | 관리자 PATCH | PASS | HTTP 200 |
| 앱 API | 작업자 화면 데이터에 반영 | PASS | HTTP 200 |
| 앱 API | 관리자 DELETE | PASS | HTTP 204 |
