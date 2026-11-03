"""Supabase Auth(/auth/v1) 호출. 로그인·토큰 검증·갱신·로그아웃을 백엔드에서만 처리한다.

브라우저는 Supabase 와 직접 통신하지 않으며 토큰을 볼 수도 없다 (토큰은 HttpOnly 쿠키에만 있다).
토큰·비밀번호는 로그나 오류 메시지에 남기지 않는다.
"""

from dataclasses import dataclass, field

import httpx

from backend import domain


@dataclass(frozen=True)
class Session:
    user_id: str
    email: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int  # 액세스 토큰 유효 시간(초)


class SupabaseAuth:
    def __init__(self, url: str, publishable_key: str, transport: httpx.BaseTransport | None = None):
        if not url or not publishable_key:
            raise RuntimeError("SUPABASE_URL 과 SUPABASE_PUBLISHABLE_KEY 가 필요합니다 (.env).")
        self._key = publishable_key
        self._http = httpx.Client(base_url=f"{url}/auth/v1", timeout=10.0, transport=transport)

    def _post(self, path: str, *, params=None, json=None, token: str | None = None) -> httpx.Response:
        headers = {"apikey": self._key}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            return self._http.post(path, params=params, json=json, headers=headers)
        except httpx.HTTPError:
            raise domain.StorageUnavailable("인증 서버에 연결할 수 없습니다.") from None

    @staticmethod
    def _session(res: httpx.Response) -> Session:
        data = res.json()
        return Session(
            user_id=data["user"]["id"],
            email=data["user"].get("email") or "",
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_in=int(data.get("expires_in", 3600)),
        )

    def sign_in(self, email: str, password: str) -> Session:
        """이메일·비밀번호 로그인 → 액세스 토큰 + 리프레시 토큰."""
        res = self._post("/token", params={"grant_type": "password"}, json={"email": email, "password": password})
        if res.status_code in (400, 401, 422):
            # 계정 존재 여부를 알려 주지 않도록 실패 이유를 하나로 통일한다.
            raise domain.Unauthorized("이메일 또는 비밀번호가 올바르지 않습니다.")
        if res.status_code == 429:
            raise domain.TooManyRequests()
        if not res.is_success:
            raise domain.StorageUnavailable(f"인증 서버 오류 (HTTP {res.status_code})")
        return self._session(res)

    def refresh(self, refresh_token: str) -> Session:
        """리프레시 토큰으로 새 토큰 한 쌍을 받는다. 사용한 리프레시 토큰은 더 이상 쓸 수 없다(rotation)."""
        res = self._post("/token", params={"grant_type": "refresh_token"}, json={"refresh_token": refresh_token})
        if res.status_code in (400, 401, 403, 422):
            raise domain.Unauthorized("로그인이 만료되었습니다. 다시 로그인하세요.")
        if not res.is_success:
            raise domain.StorageUnavailable(f"인증 서버 오류 (HTTP {res.status_code})")
        return self._session(res)

    def get_user(self, access_token: str) -> domain.CurrentUser:
        """토큰이 Supabase 가 발급한 유효한 토큰인지 Supabase 에 직접 확인한다 (서명·만료·세션 검사)."""
        try:
            res = self._http.get("/user", headers={"apikey": self._key, "Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError:
            raise domain.StorageUnavailable("인증 서버에 연결할 수 없습니다.") from None
        if res.status_code in (401, 403):
            raise domain.Unauthorized("로그인이 만료되었습니다. 다시 로그인하세요.")
        if not res.is_success:
            raise domain.StorageUnavailable(f"인증 서버 오류 (HTTP {res.status_code})")
        data = res.json()
        return domain.CurrentUser(id=data["id"], email=data.get("email"), access_token=access_token)

    def sign_out(self, access_token: str) -> None:
        """이 세션의 리프레시 토큰을 Supabase 에서 무효화한다. 실패해도 쿠키 삭제는 호출한 쪽에서 계속한다."""
        self._post("/logout", params={"scope": "local"}, token=access_token)
