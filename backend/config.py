"""환경변수(.env) 기반 설정. 비밀값은 코드에 두지 않는다."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

load_dotenv(PROJECT_ROOT / ".env")

# publishable 키는 공개용 키이며, RLS를 우회하는 secret/service_role 키는 사용하지 않는다.
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")

# 데모 로그인 계정. 서버만 알고 있고 브라우저에는 절대 내려보내지 않는다.
DEMO_ACCOUNTS = {
    "worker": (os.getenv("DEMO_WORKER_EMAIL", ""), os.getenv("DEMO_WORKER_PASSWORD", "")),
    "manager": (os.getenv("DEMO_MANAGER_EMAIL", ""), os.getenv("DEMO_MANAGER_PASSWORD", "")),
}

# 세션 쿠키에 Secure 속성(HTTPS에서만 전송)을 붙일지. 로컬 http 는 false, Render(https) 는 true.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() in ("1", "true", "yes")

# 데이터를 바꾸는 요청을 허용할 추가 출처(Origin). 기본적으로 앱 자신의 주소만 허용한다.
ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()}
