// 백엔드 API 호출 모음. 화면 코드는 이 파일의 함수만 사용하고 URL·HTTP 세부사항은 모른다.
// DB·Supabase 에는 직접 접근하지 않는다. 로그인 토큰은 HttpOnly 쿠키에 있어 이 코드에서 읽을 수 없다.
// 화면에서 버튼을 숨기는 것은 편의일 뿐이고, 실제 권한은 서버와 DB 가 판단한다.

export const AUTH_REQUIRED_EVENT = "auth-required";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function send(method, path, body) {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(errorMessage(data) || `요청 실패 (HTTP ${res.status})`, res.status);
  }
  return data;
}

// 동시에 여러 요청이 401 을 받아도 갱신은 한 번만 한다.
let refreshing = null;
function refreshSession() {
  refreshing ??= send("POST", "/api/auth/refresh").finally(() => { refreshing = null; });
  return refreshing;
}

// 데이터 요청: 401(액세스 토큰 만료)이면 한 번 갱신하고 다시 시도한다.
async function request(method, path, body) {
  try {
    return await send(method, path, body);
  } catch (err) {
    if (err.status !== 401) throw err;
    try {
      await refreshSession();
    } catch {
      window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
      throw new ApiError("로그인이 필요합니다.", 401);
    }
    return send(method, path, body);
  }
}

function errorMessage(data) {
  if (!data) return "";
  if (typeof data.detail === "string") return data.detail;
  // FastAPI 입력 검증 오류(422)는 detail 이 배열이다.
  if (Array.isArray(data.detail)) {
    if (data.detail.some((d) => d.type === "extra_forbidden")) return "허용되지 않은 입력 항목이 포함되어 있습니다.";
    return data.detail.map((d) => d.msg).join(", ");
  }
  return "";
}

const id = (reportId) => encodeURIComponent(reportId);

export const api = {
  me: () => send("GET", "/api/me"),
  demoLogin: (role) => send("POST", "/api/auth/demo", { role }),
  login: (email, password) => send("POST", "/api/auth/login", { email, password }),
  logout: () => send("POST", "/api/auth/logout"),

  listReports: (status) => request("GET", status ? `/api/reports?status=${encodeURIComponent(status)}` : "/api/reports"),
  getReport: (reportId) => request("GET", `/api/reports/${id(reportId)}`),
  createReport: (area, hazard) => request("POST", "/api/reports", { area, hazard }),
  updateReport: (reportId, changes) => request("PATCH", `/api/reports/${id(reportId)}`, changes),
  deleteReport: (reportId) => request("DELETE", `/api/reports/${id(reportId)}`),
  resetDemo: () => request("POST", "/api/demo/reset"),
};
