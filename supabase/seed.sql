-- =====================================================================
-- 데모 사업장 · 데모 계정 역할 · 시연 데이터
--
-- 먼저 할 일: Authentication → Users → Add user → Create new user 로 두 계정을 만든다
--   (Auto Confirm User 체크, 비밀번호는 .env / Render 환경변수에만 기록)
--     demo-worker@example.com   → 작업자
--     demo-manager@example.com  → 안전관리자
-- 다른 이메일을 쓰면 아래 두 곳의 이메일만 바꾼다.
-- 그다음 SQL Editor 에서 이 파일 전체를 실행한다. 다시 실행해도 안전하다(시연 데이터만 다시 채움).
-- =====================================================================

begin;

insert into public.organizations (id, name)
values ('00000000-0000-4000-8000-000000000001', '데모 사업장 (가상)')
on conflict (id) do nothing;

insert into public.profiles (user_id, organization_id, role, display_name)
select u.id, '00000000-0000-4000-8000-000000000001', v.role, v.display_name
from (values
  ('demo-worker@example.com',  'worker',  '데모 작업자'),
  ('demo-manager@example.com', 'manager', '데모 안전관리자')
) as v(email, role, display_name)
join auth.users u on lower(u.email) = v.email
on conflict (user_id) do update
  set role = excluded.role, display_name = excluded.display_name, organization_id = excluded.organization_id;

-- SQL Editor 는 마지막 결과만 보여 주므로 한 줄로 함께 출력한다.
-- demo_profiles 가 2 가 아니면 이메일·계정 생성 여부를 확인한다.
select
  private.seed_demo_reports('00000000-0000-4000-8000-000000000001') as seeded_reports,
  (select count(*) from public.profiles
    where organization_id = '00000000-0000-4000-8000-000000000001') as demo_profiles;

commit;
