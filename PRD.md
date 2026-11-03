# Safety Action Tracker — PRD

> AI 에이전트 개발 교육과정 Main Quest 1 제출용 독립 교육 프로토타입.
> 모든 데이터는 테스트 전용 가상 데이터이며 실제 기업·근로자 정보를 다루지 않는다.

## 0. 목표

작업자의 **위험요인 신고**부터 안전관리자의 **개선조치 관리**까지 하나의 흐름으로 동작하는 웹서비스를 만든다.

최우선 성공 조건

1. 실제 동작하는 웹서비스
2. 역할(작업자·안전관리자)에 따라 달라지는 화면
3. FastAPI 백엔드 API + Supabase PostgreSQL 연동
4. 서버(FastAPI)와 DB(RLS·권한) 양쪽의 권한 제어
5. 외부에서 접속 가능한 배포 URL
6. GitHub 저장소와 PRD 제출

기능 확장보다 **실제 배포와 작동 검증**을 우선한다.

## 1. 문제 정의

작업자는 현장에서 위험요인을 발견해도 기록·전달 절차가 번거롭고, 안전관리자는 접수된 위험요인의 조치 현황과 완료 여부를 계속 추적해야 한다.
본 서비스는 신고와 개선조치를 연결하여 **접수 → 조치 계획 → 진행상태 확인 → 완료**를 간단하게 수행하도록 지원한다.

## 2. 타겟 사용자

| 역할 | 설명 |
|---|---|
| 작업자 (`worker`) | 현장에서 위험요인을 발견하고 신고, 자신의 신고 진행 상태를 확인 |
| 안전관리자 (`manager`) | 사업장의 신고를 접수·관리하고 개선조치·기한·상태를 지정, 미조치·기한 경과 항목 확인 |

MVP는 두 역할만 사용하며 조직별 세부 권한 체계는 만들지 않는다.

## 3. 핵심 업무 흐름

1. 작업자 로그인
2. 작업구역과 위험요인을 입력하여 신고 → DB 저장 (상태 `received`)
3. 안전관리자 로그인 → 사업장 전체 신고 확인
4. 개선조치 내용과 조치기한 설정, 상태를 `in_progress`로 변경
5. 작업자가 내 신고 목록에서 진행 상태·조치 내용 확인
6. 조치 완료 시 안전관리자가 `completed` 처리 (완료일 자동 기록)

## 4. 역할별 기능 및 권한

| 기능 | 작업자 | 안전관리자 |
|---|---|---|
| 위험요인 신고 등록 | 가능 | 가능 |
| 본인 신고 조회 | 가능 | 가능 |
| 전체 / 타인 신고 조회 | 불가 | 가능 (소속 사업장) |
| 개선조치 내용 입력 · 조치기한 설정 | 불가 | 가능 |
| 상태 변경 · 완료 처리 | 불가 | 가능 |
| 신고 삭제 | 불가 | 가능 |
| 전체 현황 확인 | 불가 | 가능 |
| 사용자 역할 변경 | 불가 | 불가 |

- 역할은 DB `profiles` 테이블에 사전에 부여한다. 일반 사용자(인증된 사용자 포함)는 이 테이블에 INSERT/UPDATE/DELETE 권한이 없다.
- 서버는 요청 본문·쿼리·화면 상태의 role 값을 **절대 사용하지 않고**, 검증된 토큰의 사용자 ID로 DB에서 역할을 조회한다.
- 신고 생성 시에는 작업구역·위험요인 설명만 받는다. 상태·조치·기한·신고자·사업장 값을 보내면 거부된다.

## 5. 화면 구성

### A. 로그인 / 데모 접속
- 서비스명과 설명
- **작업자 데모 체험**, **안전관리자 데모 체험** 버튼 — 서버가 보관한 데모 계정으로 실제 Supabase Auth 로그인을 수행 (브라우저 코드에 비밀번호 없음)
- 이메일·비밀번호 직접 로그인 (선택)
- 로그인 후 헤더에 현재 사용자 이름·역할 표시, 로그아웃

### B. 작업자 화면 (작업자 로그인 시 기본)
- 신고 입력 폼: 작업구역, 위험요인 설명, 등록 버튼
- 내 신고 목록: 신고일, 현재 상태, 개선조치 내용, 조치기한, 완료일

### C. 안전관리자 화면 (관리자 로그인 시 기본)
- 현황 카드: 전체, 접수, 조치 중, 완료, 기한 경과
- 미조치(접수) · 기한 경과 항목 강조
- 전체 신고 목록 + 상태 필터
- 신고 상세: 신고자, 작업구역, 내용, 개선조치 입력, 조치기한, 상태 변경, 완료 처리, 삭제
- 데모 데이터 초기화

태블릿·PC 브라우저 기준 반응형, 모바일에서도 사용 가능하게 한다.

## 6. 데이터 구조 (Supabase PostgreSQL)

```
organizations 1 ──< profiles 1 ──< hazard_reports
                     (user_id = auth.users.id)
```

### organizations
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | uuid PK | 데모 사업장 ID |
| name | text | 사업장 이름 (가상) |
| created_at | timestamptz | |

### profiles
| 컬럼 | 타입 | 설명 |
|---|---|---|
| user_id | uuid PK, FK → auth.users | Supabase Auth 사용자 |
| organization_id | uuid FK → organizations | 소속 사업장 |
| role | text `worker`/`manager` | 역할 |
| display_name | text | 화면 표시 이름 |
| created_at | timestamptz | |

### hazard_reports
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid | 기본값 = 요청자 소속 사업장 |
| reported_by | uuid | 기본값 = `auth.uid()` |
| area | text (1~100자) | 작업구역 |
| hazard | text (1~1000자) | 위험요인 설명 |
| action | text (≤1000자, 최초 NULL) | 개선조치 내용 |
| status | text `received`/`in_progress`/`completed` | 기본 `received` |
| due_date | date | 조치기한 |
| completed_at | timestamptz | 완료 처리 시 트리거가 기록 |
| created_at / updated_at | timestamptz | `updated_at`은 트리거가 갱신 |

- `(reported_by, organization_id)` → `profiles(user_id, organization_id)` 복합 외래키: 신고자는 반드시 그 사업장 소속.
- `completed` 상태는 개선조치 내용이 있어야 한다 (CHECK).
- 데모 사업장 하나만 사용하지만 모든 행에 `organization_id`가 있어 다중 사업장 확장이 가능하다. 다중 사업장 관리 UI는 만들지 않는다.

## 7. 권한 및 보안

### 7-1. 구조
```
브라우저 ──(HttpOnly 쿠키)──▶ FastAPI ──(사용자 액세스 토큰)──▶ Supabase Auth / PostgREST(RLS)
```
- 브라우저는 백엔드 API만 호출한다. Supabase와 직접 통신하지 않으며 토큰을 볼 수 없다.
- 백엔드는 쿠키의 토큰을 Supabase Auth로 검증한 뒤, **사용자 본인의 토큰**으로 DB에 요청한다 → DB가 `auth.uid()` 기준으로 RLS를 적용한다.
- RLS를 우회하는 `service_role`/secret 키는 서버·코드·GitHub 어디에도 두지 않는다.

### 7-2. 이중 방어
| 위협 | FastAPI | PostgreSQL |
|---|---|---|
| 작업자가 타인 신고 조회 | — | SELECT 정책: 본인 행만 → 404 |
| 작업자가 PATCH/DELETE | 역할 검사 → 403 | UPDATE/DELETE 정책: manager만 |
| 신고 생성 시 status/action/due_date/reported_by/organization_id 지정 | 요청 스키마 `extra=forbid` → 422 | 컬럼 권한: INSERT는 `area`, `hazard`만 + INSERT 정책 초기값 검사 |
| 다른 사업장 ID 위조 | 해당 필드 수용 안 함 | 정책 `organization_id = 내 사업장` + 복합 FK |
| 역할 변경 | 해당 API 없음 | `profiles`에 INSERT/UPDATE/DELETE 권한 없음 |
| 관리자가 신고자·내용 변조 | 수정 가능 필드 제한 | 컬럼 권한: UPDATE는 `action`, `status`, `due_date`만 |
| 로그인하지 않은 요청 | 401 | `anon` 역할 권한 전부 회수 |

RLS 판단에 쓰는 `my_org()`, `my_role()` 함수는 API에 노출되지 않는 `private` 스키마에 둔다.

### 7-3. 세션 / 기타
- 토큰은 HttpOnly·SameSite 쿠키에만 저장, 배포 환경은 Secure.
- CSRF: SameSite + Origin 검사 + JSON 전용 요청.
- 비밀값은 `.env`/Render 환경변수에만 두고 Git에 올리지 않는다.
- 공개 데모 남용 방지: 입력 길이 제한(앱·DB), 요청 제한(로그인·신고 생성), 사용자당 신고 수 상한(DB 트리거), 관리자 데모 초기화 기능.

## 8. API

| 메서드 · 경로 | 설명 | 권한 |
|---|---|---|
| `GET /api/health` | 상태 확인 | 공개 |
| `GET /api/me` | 인증 상태와 사용자 역할 | 공개 (비로그인 시 `authenticated:false`) |
| `POST /api/auth/demo` | `{role}` 데모 계정 로그인 | 공개 (요청 제한) |
| `POST /api/auth/login` | 이메일·비밀번호 로그인 | 공개 (요청 제한) |
| `POST /api/auth/refresh` | 토큰 갱신 | 쿠키 |
| `POST /api/auth/logout` | 로그아웃 | 쿠키 |
| `GET /api/reports` | 신고 목록 (작업자: 본인, 관리자: 사업장 전체), `?status=` 필터 | 로그인 |
| `POST /api/reports` | 신규 신고 `{area, hazard}` | 로그인 |
| `GET /api/reports/{id}` | 신고 상세 | 로그인 (볼 수 없으면 404) |
| `PATCH /api/reports/{id}` | `{action?, status?, due_date?}` | 관리자 |
| `DELETE /api/reports/{id}` | 신고 삭제 | 관리자 |
| `POST /api/demo/reset` | 데모 신고 데이터 초기화 | 관리자 |

오류: 400/422 입력 오류, 401 미인증, 403 권한 없음, 404 없음(또는 볼 권한 없음), 415 비 JSON, 429 요청 과다, 503 저장소 오류.

## 9. 완료 조건

### 기능
- [ ] 작업자 로그인 → 작업자 화면
- [ ] 작업자 신고 등록, 새로고침 후 유지
- [ ] 관리자 로그인 → 전체 신고 목록
- [ ] 관리자 개선조치 입력·상태 변경 → 작업자 화면에 반영
- [ ] 서버 재시작 후 데이터 유지

### 보안
- [ ] 작업자가 타인 신고 ID 직접 조회 → 차단 (404)
- [ ] 작업자가 PATCH/DELETE 호출 → 차단 (API 403, DB 직접 호출도 0건/거부)
- [ ] 작업자가 자신의 역할 변경 불가 (DB 직접 호출 거부)
- [ ] 신고 생성 시 완료 상태·조치 내용 지정 불가 (API 422, DB 직접 호출 거부)
- [ ] 관리자 권한은 DB의 실제 역할 기준

### 배포
- [ ] GitHub에 PRD·소스코드, 비밀정보 없음
- [ ] 외부 접속 URL, 두 역할 체험 가능
- [ ] 배포 환경에서 저장·조회 작동

검증 결과는 `docs/VERIFICATION.md`에 실제 수행한 것만 기록한다.

## 10. 구현 제외

AI 법령 판단, 위험성평가 점수, AI 챗봇, 다중 에이전트, MCP 연동, 파일·사진 업로드, 사용자 초대, 조직 생성·다중 사업장 UI, 이메일 알림, 유료 기능, 실제 개인정보 처리.

## 11. 기술 스택

| 영역 | 선택 |
|---|---|
| 백엔드 | Python 3.11 + FastAPI (Todo 과제의 인증·쿠키·CSRF 구조 재사용) |
| 프론트엔드 | HTML · CSS · JavaScript (ES 모듈, 빌드 없음) |
| DB / 인증 | Supabase PostgreSQL + Supabase Auth (Todo와 별도 프로젝트 권장) |
| 권한 | FastAPI 역할 검증 + PostgreSQL RLS + 컬럼 권한 |
| 배포 | Render Free Web Service (데이터는 Supabase에만 저장) |

## 12. 데모 계정 방식 (결정)

**서버 측 데모 로그인**을 채택한다.

- 데모 계정 2개(작업자·관리자)를 Supabase Auth에 만들고 `profiles`에 역할을 부여한다.
- 데모 계정의 이메일·비밀번호는 서버 환경변수(`DEMO_WORKER_*`, `DEMO_MANAGER_*`)에만 있다.
- 화면의 데모 버튼은 `POST /api/auth/demo {"role":"worker"}`만 보낸다. 서버가 해당 계정으로 **실제 Supabase 로그인**을 수행하고 HttpOnly 쿠키를 설정한다.
- 이후 권한은 `role` 요청값이 아니라, 로그인된 계정의 `profiles.role`로 결정된다.

평가자에게 비밀번호를 따로 전달할 필요가 없고, 브라우저 코드에 비밀값이 없으며, 구현량이 적다(로그인 엔드포인트 1개 추가).
공유 데모 계정이므로 평가자끼리 데이터가 보일 수 있다 → 가상 데이터만 입력하도록 안내하고, 입력 제한·요청 제한·초기화로 대응한다.

## 13. 우선순위

- **P0**: PRD, 독립 저장소, FastAPI+화면, 테이블·RLS, 신고 등록·조회, 개선조치 수정, 역할 분리, API·DB 권한 검증, GitHub, 배포
- **P1**: 화면 디자인, 상태별 건수·필터, 기한 경과 표시, 모바일 대응, 데모 초기화
- **P2**: 애니메이션, 상세 대시보드, AI 기능 (P0·배포 완료 후에만)
