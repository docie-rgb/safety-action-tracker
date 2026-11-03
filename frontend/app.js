// 화면 로직. 로그인 상태(/api/me)의 역할에 따라 작업자 / 안전관리자 화면을 보여 준다.
// 사용자 입력은 textContent 로만 넣는다 (HTML 로 해석하지 않음).

import { api, AUTH_REQUIRED_EVENT } from "./api.js";

const STATUS_LABEL = { received: "접수", in_progress: "조치 중", completed: "완료" };
const ROLE_LABEL = { worker: "작업자", manager: "안전관리자" };
const FILTER_LABEL = { all: "", received: "· 접수", in_progress: "· 조치 중", completed: "· 완료", overdue: "· 기한 경과" };

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  user: null,
  reports: [],
  filter: "all",
  selectedId: null,
};

// ---------- 공통 유틸 ----------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function isOverdue(r) {
  return r.status !== "completed" && r.due_date && r.due_date < todayISO();
}

function fmtDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function fmtDue(value) {
  return value ? value.replaceAll("-", ". ") + "." : "미지정";
}

function statusBadge(status) {
  return el("span", { class: `status-badge ${status}` }, STATUS_LABEL[status] ?? status);
}

let toastTimer;
function toast(message, kind = "info") {
  const box = $("#toast");
  box.textContent = message;
  box.className = `toast ${kind}`;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, 3500);
}

async function busy(button, fn) {
  if (button) button.disabled = true;
  try {
    return await fn();
  } catch (err) {
    toast(err.message, "error");
  } finally {
    if (button) button.disabled = false;
  }
}

// ---------- 화면 전환 ----------

function show(viewId) {
  $("#loading").hidden = true;
  for (const v of $$(".view")) v.hidden = v.id !== viewId;
}

function showLogin(message) {
  state.user = null;
  state.reports = [];
  state.selectedId = null;
  $("#session").hidden = true;
  const err = $("#login-error");
  err.hidden = !message;
  err.textContent = message || "";
  show("view-login");
}

async function enter(user) {
  state.user = user;
  $("#who-name").textContent = user.display_name || user.email;
  const badge = $("#who-role");
  badge.textContent = ROLE_LABEL[user.role] ?? user.role;
  badge.className = `role-badge ${user.role}`;
  $("#session").hidden = false;
  show(user.role === "manager" ? "view-manager" : "view-worker");
  await loadReports();
}

async function loadReports() {
  try {
    state.reports = await api.listReports();
  } catch (err) {
    toast(err.message, "error");
    return;
  }
  if (state.user?.role === "manager") renderManager();
  else renderWorker();
}

// ---------- 작업자 화면 ----------

function renderWorker() {
  const list = $("#my-reports");
  list.replaceChildren(...state.reports.map(workerCard));
  $("#my-empty").hidden = state.reports.length > 0;
}

function workerCard(r) {
  const overdue = isOverdue(r);
  return el("li", { class: `report-card ${r.status}` },
    el("div", { class: "card-head" },
      statusBadge(r.status),
      overdue && el("span", { class: "overdue-badge" }, "기한 경과"),
      el("span", { class: "card-date" }, `신고 ${fmtDate(r.created_at)}`),
    ),
    el("h3", {}, r.area),
    el("p", { class: "hazard-text" }, r.hazard),
    el("div", { class: "action-box" + (r.action ? "" : " pending") },
      el("strong", {}, "개선조치"),
      el("p", {}, r.action || "안전관리자가 검토 중입니다."),
      el("div", { class: "action-meta" },
        el("span", { class: overdue ? "danger-text" : "" }, `조치기한 ${fmtDue(r.due_date)}`),
        r.completed_at && el("span", {}, `완료 ${fmtDate(r.completed_at)}`),
      ),
    ),
  );
}

// ---------- 관리자 화면 ----------

function matchesFilter(r) {
  if (state.filter === "all") return true;
  if (state.filter === "overdue") return isOverdue(r);
  return r.status === state.filter;
}

function renderManager() {
  const counts = { all: state.reports.length, received: 0, in_progress: 0, completed: 0, overdue: 0 };
  for (const r of state.reports) {
    counts[r.status] += 1;
    if (isOverdue(r)) counts.overdue += 1;
  }
  for (const [key, n] of Object.entries(counts)) $(`[data-stat="${key}"]`).textContent = n;
  for (const b of $$("#stats .stat")) b.classList.toggle("active", b.dataset.filter === state.filter);
  $("#filter-label").textContent = FILTER_LABEL[state.filter];

  const attention = state.reports.filter((r) => r.status === "received" || isOverdue(r));
  $("#attention-list").replaceChildren(...attention.map((r) =>
    el("li", {},
      el("button", { type: "button", class: "attention-item", onclick: () => select(r.id) },
        isOverdue(r) ? el("span", { class: "overdue-badge" }, "기한 경과") : statusBadge(r.status),
        el("span", { class: "att-area" }, r.area),
        el("span", { class: "att-hazard" }, r.hazard),
      ),
    ),
  ));
  $("#attention-empty").hidden = attention.length > 0;

  const rows = state.reports.filter(matchesFilter);
  $("#report-rows").replaceChildren(...rows.map((r) =>
    el("tr", {
      class: (r.id === state.selectedId ? "selected " : "") + (isOverdue(r) ? "overdue" : ""),
      tabindex: "0",
      onclick: () => select(r.id),
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(r.id); } },
    },
      el("td", { "data-label": "신고일" }, fmtDate(r.created_at)),
      el("td", { "data-label": "작업구역" }, r.area),
      el("td", { "data-label": "위험요인", class: "clip" }, r.hazard),
      el("td", { "data-label": "신고자" }, r.reporter_name || "—"),
      el("td", { "data-label": "조치기한", class: isOverdue(r) ? "danger-text" : "" }, fmtDue(r.due_date)),
      el("td", { "data-label": "상태" }, statusBadge(r.status)),
    ),
  ));
  $("#rows-empty").hidden = rows.length > 0;

  if (state.selectedId && !state.reports.some((r) => r.id === state.selectedId)) state.selectedId = null;
  renderDetail();
}

function select(reportId) {
  state.selectedId = reportId;
  renderManager();
  if (window.matchMedia("(max-width: 1199px)").matches) $("#detail").scrollIntoView({ behavior: "smooth" });
}

function renderDetail() {
  const r = state.reports.find((x) => x.id === state.selectedId);
  $("#detail-empty").hidden = Boolean(r);
  $("#detail-body").hidden = !r;
  if (!r) return;
  const badge = $("#d-status");
  badge.textContent = STATUS_LABEL[r.status];
  badge.className = `status-badge ${r.status}`;
  $("#d-area").textContent = r.area;
  $("#d-reporter").textContent = r.reporter_name || "—";
  $("#d-created").textContent = fmtDate(r.created_at);
  $("#d-completed").textContent = fmtDate(r.completed_at);
  $("#d-hazard").textContent = r.hazard;
  const form = $("#action-form");
  form.elements.action.value = r.action || "";
  form.due_date.value = r.due_date || "";
  form.status.value = r.status;
  $("#complete-btn").hidden = r.status === "completed";
}

function replaceReport(updated) {
  state.reports = state.reports.map((r) => (r.id === updated.id ? updated : r));
  renderManager();
}

async function saveDetail(extra = {}, button) {
  const form = $("#action-form");
  const changes = {
    action: form.elements.action.value.trim() || null,
    due_date: form.due_date.value || null,
    status: form.status.value,
    ...extra,
  };
  if (changes.status === "completed" && !changes.action) {
    toast("완료 처리하려면 개선조치 내용을 입력하세요.", "error");
    form.elements.action.focus();
    return;
  }
  await busy(button, async () => {
    replaceReport(await api.updateReport(state.selectedId, changes));
    toast(changes.status === "completed" ? "완료 처리했습니다." : "저장했습니다.", "success");
  });
}

// ---------- 이벤트 연결 ----------

function bindReportForms() {
  for (const form of $$("[data-report-form]")) {
    const counter = $("[data-counter]", form);
    form.hazard.addEventListener("input", () => { counter.textContent = `${form.hazard.value.length} / 1000`; });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const area = form.area.value.trim();
      const hazard = form.hazard.value.trim();
      if (!area || !hazard) {
        toast("작업구역과 위험요인 설명을 모두 입력하세요.", "error");
        return;
      }
      await busy($("button[type=submit]", form), async () => {
        const created = await api.createReport(area, hazard);
        form.reset();
        counter.textContent = "0 / 1000";
        state.reports = [created, ...state.reports];
        if (state.user.role === "manager") renderManager();
        else renderWorker();
        toast("신고가 등록되었습니다.", "success");
      });
    });
  }
}

function bind() {
  for (const btn of $$("[data-demo]")) {
    btn.addEventListener("click", () => busy(btn, async () => {
      const res = await api.demoLogin(btn.dataset.demo);
      await enter(res.user);
    }).catch(() => {}));
  }

  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    await busy($("button", form), async () => {
      const res = await api.login(form.email.value.trim(), form.password.value);
      form.reset();
      await enter(res.user);
    });
  });

  $("#logout-btn").addEventListener("click", async () => {
    await api.logout().catch(() => {});
    showLogin();
  });

  for (const b of $$("[data-refresh]")) b.addEventListener("click", () => busy(b, loadReports));

  for (const b of $$("#stats .stat")) {
    b.addEventListener("click", () => { state.filter = b.dataset.filter; renderManager(); });
  }

  $("#action-form").addEventListener("submit", (e) => {
    e.preventDefault();
    saveDetail({}, $("button[type=submit]", e.currentTarget));
  });
  $("#complete-btn").addEventListener("click", (e) => saveDetail({ status: "completed" }, e.currentTarget));

  $("#delete-btn").addEventListener("click", (e) => {
    const r = state.reports.find((x) => x.id === state.selectedId);
    if (!r || !confirm(`'${r.area}' 신고를 삭제할까요? 되돌릴 수 없습니다.`)) return;
    busy(e.currentTarget, async () => {
      await api.deleteReport(r.id);
      state.reports = state.reports.filter((x) => x.id !== r.id);
      state.selectedId = null;
      renderManager();
      toast("삭제했습니다.", "success");
    });
  });

  $("#reset-btn").addEventListener("click", (e) => {
    if (!confirm("사업장의 모든 신고를 지우고 시연용 데이터로 되돌릴까요?")) return;
    busy(e.currentTarget, async () => {
      await api.resetDemo();
      state.selectedId = null;
      state.filter = "all";
      await loadReports();
      toast("데모 데이터를 초기화했습니다.", "success");
    });
  });

  bindReportForms();
  window.addEventListener(AUTH_REQUIRED_EVENT, () => showLogin("로그인이 만료되었습니다. 다시 로그인하세요."));
}

async function start() {
  bind();
  try {
    const res = await api.me();
    if (res.authenticated) await enter(res.user);
    else showLogin();
  } catch (err) {
    showLogin(err.message);
  }
}

start();
