-- =====================================================================
-- Safety Action Tracker: Supabase(PostgreSQL) 스키마 + 권한 + RLS
--
-- 실행 위치 : Supabase 대시보드 → SQL Editor → New query → 전체 붙여 넣기 → Run
-- 실행 횟수 : 새 프로젝트에서 한 번 (begin/commit 으로 묶여 있어 실패하면 아무것도 바뀌지 않는다)
-- 다음 단계 : 데모 계정 2개를 Authentication 에서 만든 뒤 supabase/seed.sql 실행
-- =====================================================================

begin;

-- ---------------------------------------------------------------------
-- 1. 테이블
-- ---------------------------------------------------------------------

create table public.organizations (
  id         uuid primary key default gen_random_uuid(),
  name       text not null check (length(btrim(name)) > 0),
  created_at timestamptz not null default now()
);

-- 역할은 이 테이블에만 있다. 일반 사용자에게는 SELECT 권한만 준다 (아래 GRANT) → 스스로 역할 변경 불가.
create table public.profiles (
  user_id         uuid primary key references auth.users (id) on delete cascade,
  organization_id uuid not null references public.organizations (id),
  role            text not null check (role in ('worker', 'manager')),
  display_name    text not null check (length(btrim(display_name)) between 1 and 50),
  created_at      timestamptz not null default now(),
  -- hazard_reports 의 복합 외래키가 가리킬 대상
  constraint profiles_user_org_key unique (user_id, organization_id)
);

-- ---------------------------------------------------------------------
-- 2. RLS 판단용 함수 — API 로 노출되지 않는 private 스키마에 둔다.
--    security definer: profiles 의 RLS 를 거치지 않고 "요청자 자신"의 소속·역할만 읽는다
--    (정책 안에서 profiles 를 다시 조회할 때 생기는 RLS 재귀를 피한다).
-- ---------------------------------------------------------------------

create schema private;

create function private.my_org() returns uuid
  language sql stable security definer set search_path = ''
as $$ select organization_id from public.profiles where user_id = (select auth.uid()) $$;

create function private.my_role() returns text
  language sql stable security definer set search_path = ''
as $$ select role from public.profiles where user_id = (select auth.uid()) $$;

create table public.hazard_reports (
  id              uuid primary key default gen_random_uuid(),
  -- 값을 보내지 않으면 요청자의 사업장 / 요청자 자신이 들어간다 (INSERT 컬럼 권한이 없어 보낼 수도 없다)
  organization_id uuid not null default private.my_org() references public.organizations (id),
  reported_by     uuid not null default auth.uid(),
  area            text not null check (area = btrim(area) and length(area) between 1 and 100),
  hazard          text not null check (hazard = btrim(hazard) and length(hazard) between 1 and 1000),
  action          text check (action is null or (action = btrim(action) and length(action) between 1 and 1000)),
  status          text not null default 'received' check (status in ('received', 'in_progress', 'completed')),
  due_date        date,
  completed_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  -- 완료 처리에는 개선조치 내용이 필요하다
  constraint hazard_reports_completed_needs_action check (status <> 'completed' or action is not null),
  -- 신고자는 반드시 그 사업장 소속이어야 한다 → 다른 사업장 ID 로 위조 불가
  constraint hazard_reports_reporter_org_fkey
    foreign key (reported_by, organization_id)
    references public.profiles (user_id, organization_id)
    on delete cascade
);

create index hazard_reports_org_created_idx on public.hazard_reports (organization_id, created_at desc);
create index hazard_reports_reporter_idx on public.hazard_reports (reported_by);

-- ---------------------------------------------------------------------
-- 3. 트리거
-- ---------------------------------------------------------------------

-- 수정일 / 완료일 자동 기록 (클라이언트가 보낼 수 없는 값)
create function private.touch_hazard_report() returns trigger
  language plpgsql set search_path = ''
as $$
begin
  new.updated_at := now();
  if new.status = 'completed' and old.status <> 'completed' then
    new.completed_at := now();
  elsif new.status <> 'completed' then
    new.completed_at := null;
  end if;
  return new;
end $$;

create trigger hazard_reports_touch
  before update on public.hazard_reports
  for each row execute function private.touch_hazard_report();

-- 공개 데모 남용 방지: 사용자당 신고 수 상한
create function private.limit_reports_per_user() returns trigger
  language plpgsql security definer set search_path = ''
as $$
begin
  if (select count(*) from public.hazard_reports where reported_by = new.reported_by) >= 200 then
    raise exception 'report limit reached' using errcode = 'P0001', hint = 'report_limit';
  end if;
  return new;
end $$;

create trigger hazard_reports_limit
  before insert on public.hazard_reports
  for each row execute function private.limit_reports_per_user();

-- ---------------------------------------------------------------------
-- 4. 권한 (GRANT) — "이 역할이 이 테이블·컬럼에 이런 작업을 할 수 있는가"
--    anon = 비로그인 요청, authenticated = 로그인한 사용자 토큰이 있는 요청
-- ---------------------------------------------------------------------

revoke all on table public.organizations, public.profiles, public.hazard_reports from anon, authenticated;

grant select on table public.organizations, public.profiles to authenticated;   -- 역할 변경 불가
grant select, delete on table public.hazard_reports to authenticated;
grant insert (area, hazard) on table public.hazard_reports to authenticated;    -- 상태·조치·기한·신고자·사업장 지정 불가
grant update (action, status, due_date) on table public.hazard_reports to authenticated; -- 신고자·내용·사업장 변경 불가

revoke all on schema private from public;
grant usage on schema private to authenticated;
-- 함수 실행 권한은 모든 함수를 만든 뒤 7절에서 정리한다

-- ---------------------------------------------------------------------
-- 5. RLS — "어느 행에 그 작업을 할 수 있는가"
-- ---------------------------------------------------------------------

alter table public.organizations  enable row level security;
alter table public.profiles       enable row level security;
alter table public.hazard_reports enable row level security;

create policy organizations_select on public.organizations
  for select to authenticated
  using (id = (select private.my_org()));

-- 본인 프로필, 또는 관리자는 같은 사업장 사용자 프로필(신고자 이름 표시용)
create policy profiles_select on public.profiles
  for select to authenticated
  using (
    user_id = (select auth.uid())
    or (organization_id = (select private.my_org()) and (select private.my_role()) = 'manager')
  );

-- 작업자: 본인 신고만 / 관리자: 소속 사업장 전체
create policy hazard_reports_select on public.hazard_reports
  for select to authenticated
  using (
    organization_id = (select private.my_org())
    and (reported_by = (select auth.uid()) or (select private.my_role()) = 'manager')
  );

-- 본인 ID·본인 사업장으로만, 초기 상태로만 생성 (컬럼 권한에 더한 이중 방어)
create policy hazard_reports_insert on public.hazard_reports
  for insert to authenticated
  with check (
    reported_by = (select auth.uid())
    and organization_id = (select private.my_org())
    and status = 'received'
    and action is null
    and due_date is null
    and completed_at is null
  );

create policy hazard_reports_update on public.hazard_reports
  for update to authenticated
  using      (organization_id = (select private.my_org()) and (select private.my_role()) = 'manager')
  with check (organization_id = (select private.my_org()) and (select private.my_role()) = 'manager');

create policy hazard_reports_delete on public.hazard_reports
  for delete to authenticated
  using (organization_id = (select private.my_org()) and (select private.my_role()) = 'manager');

-- ---------------------------------------------------------------------
-- 6. 데모 데이터
-- ---------------------------------------------------------------------

-- 사업장의 신고를 모두 지우고 가상 시연 데이터로 다시 채운다 (seed.sql 과 reset_demo_data 가 사용)
create function private.seed_demo_reports(org uuid) returns integer
  language plpgsql security definer set search_path = ''
as $$
declare
  w uuid;
  n integer;
begin
  select user_id into w from public.profiles
   where organization_id = org and role = 'worker' order by created_at limit 1;
  if w is null then
    raise exception 'no worker profile in organization';
  end if;

  delete from public.hazard_reports where organization_id = org;

  -- 날짜는 실행 시점 기준 상대값: due_in = 오늘부터 조치기한까지 일수(음수면 기한 경과), *_ago = 며칠 전
  insert into public.hazard_reports
    (organization_id, reported_by, area, hazard, action, status, due_date, completed_at, created_at)
  select org, w, v.area, v.hazard, v.action, v.status,
         current_date + v.due_in,
         now() - make_interval(days => v.completed_ago),
         now() - make_interval(days => v.created_ago, hours => v.hours_ago)
  from (values
    -- 접수 (조치 전)
    ('B동 출입구', '우천 시 출입구 바닥이 미끄러운데 미끄럼 방지 매트가 없음', null::text, 'received', null::int, null::int, 0, 3),
    ('A동 2층 계단', '계단 난간 고정 볼트가 풀려 흔들림', null, 'received', null, null, 1, 2),
    ('프레스 작업장', '2호기 프레스 양수조작 버튼 한쪽이 테이프로 눌린 채 고정되어 있음', null, 'received', null, null, 2, 5),
    ('옥상', '옥상 출입문 옆 안전난간 일부 구간이 철거된 채 방치됨', null, 'received', null, null, 2, 1),
    ('전기실', '분전반 앞에 박스가 쌓여 차단기 조작 공간이 확보되지 않음', null, 'received', null, null, 4, 6),
    ('휴게실', '전기 포트용 멀티탭이 문어발식으로 연결되어 있고 피복 일부가 손상됨', null, 'received', null, null, 5, 4),
    -- 조치 중 (일부 기한 경과)
    ('자재 창고', '통로에 팔레트가 적재되어 비상구 동선이 막힘', '팔레트 재배치 및 통로 바닥 표시', 'in_progress', 3, null, 3, 2),
    ('도장 부스', '유기용제 용기 뚜껑이 열린 채 보관되어 냄새가 심함', '밀폐 용기로 교체하고 MSDS 게시 위치 재정비', 'in_progress', 5, null, 4, 7),
    ('고소작업 구역', '이동식 비계 바퀴 고정장치 1개가 파손됨', '해당 비계 사용 중지 표지 부착, 고정장치 교체 예정', 'in_progress', 7, null, 5, 3),
    ('C동 지게차 충전소', '충전 구역에 소화기가 비치되어 있지 않음', '분말소화기 2대 비치 요청, 점검표 부착 예정', 'in_progress', 2, null, 6, 5),
    ('용접 작업장', '국소배기장치 흡입력 약화', '필터 교체 및 풍량 측정', 'in_progress', -2, null, 7, 4),
    ('컨베이어 라인', '3번 컨베이어 끝단 비상정지 스위치 작동 불량', '비상정지 스위치 교체 부품 발주 완료', 'in_progress', -1, null, 9, 2),
    ('화학물질 보관실', '산·알칼리 약품이 같은 선반에 섞여 보관됨', '성상별 분리 보관 선반 설치 진행 중', 'in_progress', -4, null, 12, 6),
    -- 완료
    ('지게차 통로', '보행자 통로 구분선이 지워짐', '구분선 재도색 완료', 'completed', -5, 4, 10, 3),
    ('기계 가공실', '연삭기 덮개가 분리된 채 사용 중', '덮개 재설치, 작업 전 점검 항목에 추가', 'completed', -8, 9, 14, 5),
    ('주차장 진입로', '야간 조명 2개가 꺼져 보행자 식별이 어려움', '조명 교체 완료', 'completed', -10, 11, 16, 2),
    ('포장 라인', '밴딩기 칼날 부위에 방호커버가 없음', '방호커버 설치 및 작업자 교육 실시', 'completed', -12, 13, 20, 4),
    ('A동 1층 복도', '소화전 앞 적재물 때문에 소화전을 열 수 없음', '적재물 이동, 소화전 앞 적재 금지 표시', 'completed', -15, 18, 22, 6),
    ('폐기물 집하장', '날카로운 금속 스크랩이 일반 마대에 담겨 있음', '스크랩 전용 철제 용기 비치', 'completed', -18, 17, 25, 3),
    ('탈의실', '비상구 유도등이 점등되지 않음', '유도등 배터리 교체', 'completed', -20, 24, 28, 5)
  ) as v(area, hazard, action, status, due_in, completed_ago, created_ago, hours_ago);

  get diagnostics n = row_count;
  return n;
end $$;

-- 관리자 전용 데모 초기화 (API: POST /api/demo/reset → /rest/v1/rpc/reset_demo_data)
create function public.reset_demo_data() returns integer
  language plpgsql security definer set search_path = ''
as $$
begin
  if (select private.my_role()) is distinct from 'manager' then
    raise exception 'manager only' using errcode = '42501';
  end if;
  return private.seed_demo_reports((select private.my_org()));
end $$;

revoke all on function public.reset_demo_data() from public, anon;
grant execute on function public.reset_demo_data() to authenticated;

-- ---------------------------------------------------------------------
-- 7. private 함수 실행 권한: RLS·컬럼 기본값에 필요한 두 함수만 로그인 사용자에게 허용
--    (나머지는 security definer 함수·트리거 안에서만 쓰인다)
-- ---------------------------------------------------------------------

revoke all on all functions in schema private from public, anon, authenticated;
grant execute on function private.my_org(), private.my_role() to authenticated;

commit;
