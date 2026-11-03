# Safety Action Tracker

작업자의 **위험요인 신고**부터 안전관리자의 **개선조치 관리**까지 하나의 흐름으로 처리하는 산업안전 웹서비스입니다.
AI 에이전트 개발 교육과정 Main Quest 1 제출용 독립 교육 프로토타입이며, 모든 데이터는 가상 데이터입니다.

- **배포 URL**: _(배포 후 기재)_
- **요구사항 문서**: [PRD.md](PRD.md)
- **검증 결과**: [docs/VERIFICATION.md](docs/VERIFICATION.md)

## 데모 접속 방법

1. 배포 URL에 접속합니다. (Render 무료 인스턴스라 첫 접속에 최대 1분 정도 걸릴 수 있습니다)
2. **작업자 데모 체험** → 위험요인을 신고하고 내 신고 내역을 확인합니다.
3. 우측 상단 **로그아웃** → **안전관리자 데모 체험** → 신고를 선택해 개선조치·조치기한·상태를 입력하고 저장합니다.
4. 다시 작업자로 로그인하면 변경된 상태와 조치 내용이 보입니다.

데모 버튼은 서버에 등록된 테스트 계정으로 **실제 Supabase 로그인**을 수행합니다. 비밀번호는 서버 환경변수에만 있고 브라우저 코드에는 없습니다.
권한은 버튼 값이 아니라 로그인된 계정의 DB 역할(`profiles.role`)로 결정됩니다.
데모 계정은 평가자들이 공유하므로 가상의 내용만 입력해 주세요. 관리자 화면 하단 **데모 데이터 초기화**로 시연 데이터를 되돌릴 수 있습니다.

## 주요 기능

| 작업자 | 안전관리자 |
|---|---|
| 작업구역·위험요인 신고 | 전체/접수/조치 중/완료/기한 경과 건수 (클릭 시 필터) |
| 내 신고 목록, 진행 상태 | 미조치·기한 경과 항목 강조 |
| 개선조치 내용·조치기한·완료일 확인 | 신고 상세, 개선조치·조치기한 입력, 상태 변경, 완료 처리, 삭제 |
| | 직접 신고 등록, 데모 데이터 초기화 |

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 백엔드 | Python 3.11, FastAPI, httpx |
| 프론트엔드 | HTML, CSS, JavaScript (ES 모듈, 빌드 도구 없음) |
| DB · 인증 | Supabase PostgreSQL, Supabase Auth |
| 권한 | FastAPI 역할 검사 + PostgreSQL RLS + 컬럼 권한 |
| 배포 | Render Free Web Service |
| 테스트 | pytest (+ 실제 Supabase 대상 검증 스크립트) |

```
브라우저 ──(HttpOnly 쿠키)──▶ FastAPI (Render) ──(사용자 토큰)──▶ Supabase Auth / PostgreSQL(RLS)
```

## 화면 구성

- **로그인**: 서비스 소개, 작업자/안전관리자 데모 버튼, 이메일 로그인
- **작업자**: 신고 입력 폼 + 내 신고 카드 목록
- **안전관리자**: 현황 카드, 조치 필요 목록, 전체 신고 표, 상세·조치 입력 패널 (태블릿·모바일에서는 세로 배치, 표는 카드로 변환)

## 프로젝트 구조

```
backend/
  main.py            FastAPI 앱, CSRF·보안 헤더 미들웨어, 정적 파일
  api/auth.py        /api/me, 로그인·데모 로그인·갱신·로그아웃
  api/reports.py     신고 CRUD, 데모 초기화
  api/deps.py        토큰 검증 → DB 역할 조회, 관리자 확인
  repository.py      Supabase REST 호출 (사용자 토큰 전달)
  supabase_auth.py   Supabase Auth 호출
  ratelimit.py       로그인·신고 요청 제한
frontend/            index.html, app.js, api.js, styles.css
supabase/schema.sql  테이블·트리거·권한·RLS
supabase/seed.sql    데모 사업장·역할·시연 데이터
scripts/rls_check.py 실제 DB·API 권한 검증
tests/               pytest
```

## 데이터베이스 구성

| 테이블 | 주요 컬럼 |
|---|---|
| `organizations` | `id`, `name` |
| `profiles` | `user_id`(auth.users), `organization_id`, `role`(worker/manager), `display_name` |
| `hazard_reports` | `id`, `organization_id`, `reported_by`, `area`, `hazard`, `action`, `status`(received/in_progress/completed), `due_date`, `completed_at`, `created_at`, `updated_at` |

- `reported_by`·`organization_id` 기본값은 DB가 채웁니다 (`auth.uid()`, 요청자 소속 사업장).
- `(reported_by, organization_id)` 복합 외래키로 신고자는 반드시 같은 사업장 소속입니다.
- `updated_at`·`completed_at`은 트리거가 기록하고, 완료 상태는 개선조치 내용이 있어야 합니다(CHECK).

## 권한 검증 방법

보안은 화면에서 버튼을 숨기는 것이 아니라 **서버와 DB 양쪽**에서 적용됩니다.

| 공격 | FastAPI | PostgreSQL |
|---|---|---|
| 작업자가 타인 신고 ID 조회 | — | RLS: 본인 행만 → 404 |
| 작업자가 PATCH/DELETE | 403 | RLS: manager만 수정·삭제 |
| 신고 생성 시 status·action·due_date·reported_by·organization_id 지정 | 422 (`extra=forbid`) | INSERT 컬럼 권한 `area`,`hazard`만 + 정책 초기값 검사 |
| 역할 변경 | API 없음 | `profiles` 쓰기 권한 없음 |
| 다른 사업장 위조 | 필드 거부 | 정책 + 복합 FK |
| 관리자가 신고자·내용 변조 | 필드 거부 | UPDATE 컬럼 권한 `action`,`status`,`due_date`만 |

- RLS를 우회하는 `service_role`/secret 키는 사용하지 않습니다. 백엔드는 사용자 본인의 토큰으로 DB에 요청합니다.
- 토큰은 HttpOnly·SameSite(배포 시 Secure) 쿠키에만 저장합니다. CSRF는 Origin 검사 + JSON 전용 요청으로 한 번 더 막습니다.

직접 확인:

```bash
.venv/Scripts/python -m pytest -q
```

```bash
.venv/Scripts/python -m scripts.rls_check
```

`rls_check`는 데모 계정의 일반 사용자 토큰으로 Supabase REST를 직접 호출해 위 공격들이 DB에서 막히는지 확인하고, 서버가 실행 중이면 앱 API로도 확인합니다. 결과는 `docs/rls_check_result.md`에 저장됩니다.

## 실행 방법 (로컬)

1. Supabase 프로젝트를 만들고 SQL Editor에서 `supabase/schema.sql`을 실행합니다.
2. Authentication → Users → Add user로 `demo-worker@example.com`, `demo-manager@example.com`을 만듭니다 (Auto Confirm 체크).
3. SQL Editor에서 `supabase/seed.sql`을 실행합니다 (결과 `demo_profiles = 2` 확인).
4. Authentication → Sign In / Providers에서 **Allow new users to sign up**을 끕니다 (외부 가입 차단).
5. 환경 설정 및 실행:

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt
```

```bash
cp .env.example .env
```

`.env`에 `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`(publishable 키만), 데모 계정 비밀번호를 입력한 뒤:

```bash
.venv/Scripts/python -m uvicorn backend.main:app --reload
```

http://127.0.0.1:8000 에 접속합니다.

## 배포 (Render)

`render.yaml` Blueprint 또는 Web Service 수동 생성:

| 항목 | 값 |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/api/health` |
| 환경변수 | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `DEMO_WORKER_EMAIL/PASSWORD`, `DEMO_MANAGER_EMAIL/PASSWORD`, `COOKIE_SECURE=true`, `PYTHON_VERSION=3.11.9` |

데이터는 Supabase에만 저장되므로 Render 재시작·재배포 후에도 유지됩니다.

## 공개 데모 남용 방지

- 입력 길이 제한 (작업구역 100자, 설명·조치 1000자 — 앱과 DB 모두)
- 요청 제한: IP당 10분 로그인 20회, 사용자당 10분 신고 20건 (429)
- DB 트리거: 사용자당 신고 최대 200건
- 관리자 데모 초기화 (`POST /api/demo/reset`)
- 외부 회원가입 비활성화

## 구현 제외 (향후 확장)

AI 법령 판단, 위험성평가 점수, 챗봇, 파일·사진 업로드, 사용자 초대, 다중 사업장 관리 UI, 이메일 알림.
