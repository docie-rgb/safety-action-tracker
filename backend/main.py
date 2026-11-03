"""FastAPI 진입점: /api/* 는 JSON API, 그 외 경로는 frontend/ 정적 파일."""

from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import config, domain
from backend.api import auth, reports

app = FastAPI(title="Safety Action Tracker API")

_STATUS = {
    domain.ValidationError: 400,
    domain.NotFound: 404,
    domain.Unauthorized: 401,
    domain.PermissionDenied: 403,
    domain.TooManyRequests: 429,
    domain.StorageUnavailable: 503,
}

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """쿠키 로그인을 노린 CSRF(다른 사이트가 몰래 보내는 요청) 방어. SameSite 쿠키에 더한 이중 방어.

    1) Origin 검사: 앱 자신의 주소(또는 ALLOWED_ORIGINS)가 아니면 거부한다.
    2) JSON 만 허용: 일반 HTML 폼은 JSON 을 보낼 수 없고, 다른 출처의 JSON 요청은 CORS 사전 확인에서 막힌다.
    """
    if request.method in _UNSAFE_METHODS and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin is not None:
            own_host = request.headers.get("host", "")
            if urlsplit(origin).netloc != own_host and origin.rstrip("/") not in config.ALLOWED_ORIGINS:
                return JSONResponse(status_code=403, content={"detail": "허용되지 않은 출처의 요청입니다."})
        has_body = (
            request.headers.get("content-length", "0") not in ("", "0") or "transfer-encoding" in request.headers
        )
        content_type = request.headers.get("content-type", "")
        if has_body and not content_type.startswith("application/json"):
            return JSONResponse(status_code=415, content={"detail": "JSON 형식의 요청만 허용됩니다."})
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(domain.DomainError)
async def domain_error_handler(request: Request, exc: domain.DomainError):
    return JSONResponse(status_code=_STATUS.get(type(exc), 400), content={"detail": str(exc)})


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(reports.router)

# 반드시 API 라우터 등록 뒤에 마운트한다 (먼저 마운트하면 /api 요청을 가로챈다).
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
