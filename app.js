/*
 * Engineer A - Student Portal
 * Configure API_BASE_URL before connecting to Engineer B's backend.
 * The frontend never decides attendance validity or On Time/Late status.
 */
const CONFIG = {
  // Same origin as the page, so phones/tablets on the LAN hit the PC that served it.
  // Opened from file:// there is no origin to borrow, so fall back to the dev server.
  API_BASE_URL: (() => {
    const { protocol, origin } = window.location;
    if (protocol === "http:" || protocol === "https:") return `${origin}/api/v1`;
    return "http://localhost:8000/api/v1";
  })(),
  // Keep false for integration/testing. Do not use demo mode for real attendance.
  DEMO_MODE: false,
  // Keep false for production: an access token in browser storage can be read by XSS.
  // Set true only for local demos so a page refresh does not sign you out.
  PERSIST_SESSION: false,
  SESSION_STORAGE_KEY: "attendly.session",
  // html5-qrcode uses the device browser camera. HTTPS is required outside localhost.
};

const state = {
  token: null,
  student: null,
  records: [],            // dashboard month
  historyRecords: [],     // month picked in the history filter
  totalSessions: null,
  scanner: null,
  scannerRunning: false,
  currentView: "dashboard",
  scanLocked: false,
  busy: false,
};

const $ = (id) => document.getElementById(id);
const apiUrl = (path) => `${CONFIG.API_BASE_URL}${path}`;

const WAT_TIMEZONE = "Africa/Lagos";

function normalizeUsername(value) {
  return String(value || "").toLowerCase().replace(/\s+/g, "");
}
function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
/* Month key (YYYY-MM) in West Africa Time, so the "current month" matches the school's clock. */
function watMonthKey(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 7);
  const parts = new Intl.DateTimeFormat("en-CA", {timeZone: WAT_TIMEZONE, year: "numeric", month: "2-digit"}).formatToParts(date);
  const get = (type) => parts.find(p => p.type === type)?.value;
  return `${get("year")}-${get("month")}`;
}
function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2800);
}
function showAuthAlert(message, success = false) {
  const box = $("authAlert");
  box.textContent = message;
  box.classList.toggle("success", success);
  box.classList.remove("hidden");
}
function clearAuthAlert() { $("authAlert").classList.add("hidden"); }
function setConnectionNote(message) { $("connectionNote").textContent = message; }

function saveSession() {
  if (!CONFIG.PERSIST_SESSION) return;
  try {
    window.sessionStorage.setItem(CONFIG.SESSION_STORAGE_KEY, JSON.stringify({token: state.token, student: state.student}));
  } catch {}
}
function clearSession() {
  try { window.sessionStorage.removeItem(CONFIG.SESSION_STORAGE_KEY); } catch {}
}
function restoreSession() {
  if (!CONFIG.PERSIST_SESSION) return false;
  try {
    const raw = window.sessionStorage.getItem(CONFIG.SESSION_STORAGE_KEY);
    if (!raw) return false;
    const saved = JSON.parse(raw);
    if (!saved?.token || !saved?.student) return false;
    state.token = saved.token;
    state.student = saved.student;
    return true;
  } catch { return false; }
}

async function apiRequest(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let response;
  try {
    response = await fetch(apiUrl(path), { ...options, headers });
  } catch {
    const error = new Error("Cannot reach the attendance server. Check your connection or API address.");
    error.network = true;
    throw error;
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail || body.message || body.error || "The request could not be completed.";
    const error = new Error(typeof detail === "string" ? detail : "Please check your details and try again.");
    error.status = response.status;
    error.body = body;
    if (response.status === 401 && state.token) {
      // Token expired or was revoked: drop it and send the student back to sign in.
      state.token = null;
      state.student = null;
      clearSession();
      error.sessionExpired = true;
    }
    throw error;
  }
  return body;
}

function switchAuth(mode) {
  clearAuthAlert();
  $("loginForm").classList.toggle("hidden", mode !== "login");
  $("registerForm").classList.toggle("hidden", mode !== "register");
  document.querySelectorAll(".auth-tab").forEach(tab => tab.classList.toggle("active", tab.dataset.auth === mode));
}
function showApp() {
  $("authScreen").classList.add("hidden");
  $("topName").textContent = state.student.full_name;
  $("topUsername").textContent = `@${state.student.username}`;
  $("topAvatar").textContent = String(state.student.full_name || "?").trim().charAt(0).toUpperCase();
  $("welcomeName").textContent = String(state.student.full_name || "").split(" ")[0];
  $("profileName").textContent = state.student.full_name;
  $("profileUsername").textContent = state.student.username;
  showView("dashboard");
  loadDashboard();
}
function showAuth() {
  $("authScreen").classList.remove("hidden");
  stopScanner();
}
function showView(name) {
  if (!$(`${name}View`)) name = "dashboard";
  state.currentView = name;
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  $(`${name}View`).classList.add("active");
  document.querySelectorAll(".nav-item[data-view]").forEach(b => b.classList.toggle("active", b.dataset.view === name));
  $("pageTitle").textContent = ({dashboard:"Dashboard",scanner:"Scan attendance",history:"Attendance history"})[name] || "Dashboard";
  $("sidebar").classList.remove("open");
  if (name !== "scanner") stopScanner();
  if (name === "history") renderHistory();
}

async function registerStudent(event) {
  event.preventDefault();
  if (state.busy) return;
  clearAuthAlert();
  const fullName = $("fullName").value.trim().replace(/\s+/g, " ");
  const username = normalizeUsername($("registerUsername").value);
  const password = $("registerPassword").value;
  const confirm = $("confirmPassword").value;
  if (fullName.length < 2) return showAuthAlert("Enter your full name as it appears on your student record.");
  if (!/^[a-z0-9_-]{3,30}$/.test(username)) return showAuthAlert("Username must be 3–30 characters and contain only lowercase letters, numbers, underscores or hyphens. Spaces are removed automatically.");
  if (password.length < 8) return showAuthAlert("Your password must contain at least 8 characters.");
  if (password !== confirm) return showAuthAlert("The passwords do not match.");

  const button = event.submitter || $("registerFormEl").querySelector('button[type="submit"]');
  const label = button.innerHTML;
  state.busy = true; button.disabled = true; button.textContent = "Creating account…";
  try {
    const result = await apiRequest("/auth/register", {method:"POST", body:JSON.stringify({full_name:fullName, username, password})});
    $("registerPassword").value = "";
    $("confirmPassword").value = "";
    if (result.access_token && (result.student || result.user)) {
      state.token = result.access_token;
      state.student = result.student || result.user;
      saveSession();
      showApp();
      showToast("Your account has been created.");
    } else {
      showAuthAlert("Account created. Please sign in with your new details.", true);
      switchAuth("login");
      $("loginUsername").value = username;
      $("loginPassword").focus();
    }
  } catch (error) {
    showAuthAlert(error.message);
  } finally {
    state.busy = false; button.disabled = false; button.innerHTML = label;
  }
}

async function loginStudent(event) {
  event.preventDefault();
  if (state.busy) return;
  clearAuthAlert();
  const username = normalizeUsername($("loginUsername").value);
  const password = $("loginPassword").value;
  if (!username || !password) return showAuthAlert("Enter your attendance username and password.");
  const button = event.submitter || $("loginFormEl").querySelector('button[type="submit"]');
  const label = button.innerHTML;
  state.busy = true; button.disabled = true; button.textContent = "Signing in…";
  try {
    const result = await apiRequest("/auth/login", {method:"POST", body:JSON.stringify({username, password})});
    state.token = result.access_token;
    state.student = result.student || result.user;
    if (!state.token || !state.student) throw new Error("The login response is missing access_token or student details. See API_CONTRACT.md.");
    $("loginPassword").value = "";
    saveSession();
    showApp();
    showToast("Welcome back!");
  } catch (error) {
    showAuthAlert(error.message);
  } finally {
    state.busy = false; button.disabled = false; button.innerHTML = label;
  }
}

function handleSessionExpired() {
  state.records = []; state.historyRecords = []; state.totalSessions = null;
  showAuth();
  switchAuth("login");
  showAuthAlert("Your session ended. Please sign in again.");
}

async function loadDashboard() {
  const month = watMonthKey();
  try {
    const result = await apiRequest(`/students/me/attendance?month=${encodeURIComponent(month)}`);
    state.records = result.records || result.items || [];
    state.totalSessions = result.total_sessions ?? null;
    renderDashboard();
    if ($("monthFilter").value === month) {
      state.historyRecords = state.records;
      renderHistory();
    }
  } catch (error) {
    if (error.sessionExpired) return handleSessionExpired();
    if (state.token) showToast(error.message);
    renderDashboard();
  }
}

function recordStatus(record) {
  return String(record.status || (record.is_late ? "late" : "on_time")).toLowerCase();
}
function isLate(record) { return recordStatus(record) === "late"; }
function statusMarkup(record) {
  return `<span class="status-pill ${isLate(record) ? "late" : "on-time"}">${isLate(record) ? "Late" : "On Time"}</span>`;
}
function recordDate(record) {
  return record.attended_at || record.timestamp || record.checked_in_at || record.scan_time || record.date || "";
}
function watParts(value) {
  if (!value) return {date:"—",time:"—"};
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return {date:String(value),time:"—"};
  return {
    date:new Intl.DateTimeFormat("en-GB",{timeZone:WAT_TIMEZONE,day:"2-digit",month:"short",year:"numeric"}).format(date),
    time:new Intl.DateTimeFormat("en-GB",{timeZone:WAT_TIMEZONE,hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}).format(date)
  };
}
function renderRows(target, records) {
  const body = $(target);
  if (!records.length) { body.innerHTML = '<tr><td colspan="4" class="empty-cell">No attendance records found.</td></tr>'; return; }
  body.innerHTML = records.map(r => {
    const t = watParts(recordDate(r));
    const session = r.session_name || r.session?.name || "Attendance session";
    return `<tr><td><strong>${escapeHtml(session)}</strong></td><td>${escapeHtml(t.date)}</td><td>${escapeHtml(t.time)}</td><td>${statusMarkup(r)}</td></tr>`;
  }).join("");
}
function renderDashboard() {
  const records = state.records;
  const onTime = records.filter(r => !isLate(r)).length;
  const late = records.length - onTime;
  $("statAttended").textContent = records.length;
  $("statOnTime").textContent = onTime;
  $("statLate").textContent = late;
  // Attendance rate needs the total number of sessions from the server; never invent a denominator.
  const total = Number(state.totalSessions);
  $("statRate").textContent = Number.isFinite(total) && total > 0
    ? `${Math.min(100, Math.round(records.length / total * 100))}%`
    : "—";
  renderRows("recentRows", records.slice(0,5));
}
function renderHistory() {
  const month = $("monthFilter").value || watMonthKey();
  const filtered = state.historyRecords.filter(r => watMonthKey(recordDate(r)) === month);
  renderRows("historyRows", filtered);
  $("historyCount").textContent = `${filtered.length} record${filtered.length === 1 ? "" : "s"}`;
}
async function refreshAttendance() {
  const month = $("monthFilter").value || watMonthKey();
  try {
    const result = await apiRequest(`/students/me/attendance?month=${encodeURIComponent(month)}`);
    state.historyRecords = result.records || result.items || [];
    if (month === watMonthKey()) {
      state.records = state.historyRecords;
      state.totalSessions = result.total_sessions ?? state.totalSessions;
      renderDashboard();
    }
    renderHistory();
  } catch (error) {
    if (error.sessionExpired) return handleSessionExpired();
    showToast(error.message);
    renderHistory();
  }
}

async function startScanner() {
  const notice = $("scanNotice");
  notice.classList.add("hidden");
  if (!window.Html5Qrcode) { notice.textContent = "The QR scanner library did not load. Check your internet connection and refresh."; notice.classList.remove("hidden"); return; }
  if (state.scanLocked) { notice.textContent = "Your previous scan is being verified. Please wait."; notice.classList.remove("hidden"); return; }
  if (state.scannerRunning) return;
  try {
    if (!state.scanner) state.scanner = new window.Html5Qrcode("reader");
    const cameras = await window.Html5Qrcode.getCameras();
    if (!cameras || !cameras.length) throw new Error("No camera was found on this device.");
    const camera = cameras.find(c => /back|rear|environment/i.test(c.label || "")) || cameras[cameras.length - 1];
    await state.scanner.start(camera.id, {fps:10,qrbox:{width:230,height:230},aspectRatio:1.0}, onQrDecoded, () => {});
    state.scannerRunning = true;
    $("startScanBtn").disabled = true; $("stopScanBtn").disabled = false;
  } catch (error) {
    notice.textContent = error?.message || "Could not start the camera. Check browser permissions and use HTTPS.";
    notice.classList.remove("hidden");
    $("startScanBtn").disabled = false; $("stopScanBtn").disabled = true;
  }
}
async function stopScanner() {
  if (state.scanner && state.scannerRunning) {
    try { await state.scanner.stop(); } catch {}
    state.scannerRunning = false;
  }
  if ($("startScanBtn")) $("startScanBtn").disabled = false;
  if ($("stopScanBtn")) $("stopScanBtn").disabled = true;
}
async function onQrDecoded(decodedText) {
  // The scanner is stopped after a decode, so a second callback can only mean a
  // very fast repeat frame. The server is the authority on duplicates, so let it answer.
  if (state.scanLocked) return;
  state.scanLocked = true;
  await stopScanner();
  const notice = $("scanNotice");
  notice.textContent = "QR captured. Verifying your attendance…";
  notice.classList.remove("hidden");
  try {
    const result = await apiRequest("/attendance/check-in", {method:"POST",body:JSON.stringify({qr_payload:decodedText})});
    if (result.already_checked_in || result.code === "DUPLICATE_ATTENDANCE") {
      notice.textContent = "Already checked in for this session. Your existing attendance record has not been changed.";
      showToast("Already checked in for this session.");
      return;
    }
    notice.classList.add("hidden");
    showConfirmation(result);
    await loadDashboard();
  } catch (error) {
    if (error.sessionExpired) return handleSessionExpired();
    const duplicate = error.body?.already_checked_in || error.body?.code === "DUPLICATE_ATTENDANCE" || /already|duplicate|checked in/i.test(error.message);
    notice.textContent = duplicate ? "Already checked in for this session." : error.message;
    if (duplicate) showToast("Already checked in for this session.");
  } finally {
    state.scanLocked = false;
  }
}
function showConfirmation(result) {
  const student = result.student || state.student || {};
  const stamp = result.attended_at || result.timestamp || result.checked_in_at || new Date().toISOString();
  const parts = watParts(stamp);
  const late = String(result.status || (result.is_late ? "late" : "on_time")).toLowerCase() === "late";
  $("confirmName").textContent = student.full_name || "—";
  $("confirmUsername").textContent = student.username || "—";
  $("confirmSession").textContent = result.session_name || result.session?.name || "Current session";
  $("confirmDate").textContent = result.date || parts.date;
  $("confirmTime").textContent = result.time_wat || parts.time;
  $("confirmStatus").textContent = late ? "LATE" : "ON TIME";
  $("confirmStatus").classList.toggle("late", late);
  $("confirmationModal").classList.remove("hidden");
  $("closeConfirmation").focus();
}
function closeConfirmation(goDashboard = true) {
  $("confirmationModal").classList.add("hidden");
  if (goDashboard) showView("dashboard");
}
async function logout() {
  try { await apiRequest("/auth/logout",{method:"POST",body:"{}"}); } catch {}
  state.token = null; state.student = null; state.records = []; state.historyRecords = []; state.totalSessions = null;
  clearSession();
  showAuth(); switchAuth("login"); showView("dashboard");
}

document.addEventListener("DOMContentLoaded", () => {
  $("year").textContent = new Date().getFullYear();
  $("monthFilter").value = watMonthKey();
  switchAuth("login");
  setConnectionNote(CONFIG.DEMO_MODE
    ? "Demo mode · records stay in this browser only"
    : `API: ${CONFIG.API_BASE_URL} · Configure this address to match Engineer B's server.`);

  document.querySelectorAll("[data-auth]").forEach(b => b.addEventListener("click", () => switchAuth(b.dataset.auth)));
  document.querySelectorAll("[data-view]").forEach(b => b.addEventListener("click", () => showView(b.dataset.view)));
  document.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => showView(b.dataset.go)));
  $("registerUsername").addEventListener("input", e => { const p = e.target.selectionStart; e.target.value = normalizeUsername(e.target.value); e.target.setSelectionRange(p, p); });
  $("loginUsername").addEventListener("input", e => { const p = e.target.selectionStart; e.target.value = normalizeUsername(e.target.value); e.target.setSelectionRange(p, p); });
  $("registerFormEl").addEventListener("submit", registerStudent);
  $("loginFormEl").addEventListener("submit", loginStudent);
  $("dashboardScanBtn").addEventListener("click", () => showView("scanner"));
  $("startScanBtn").addEventListener("click", startScanner);
  $("stopScanBtn").addEventListener("click", stopScanner);
  $("logoutBtn").addEventListener("click", logout);
  $("menuBtn").addEventListener("click", () => $("sidebar").classList.toggle("open"));
  $("monthFilter").addEventListener("change", refreshAttendance);
  $("closeConfirmation").addEventListener("click", () => closeConfirmation());
  $("confirmationModal").addEventListener("click", e => { if (e.target === $("confirmationModal")) closeConfirmation(false); });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !$("confirmationModal").classList.contains("hidden")) closeConfirmation(false);
  });

  if (restoreSession()) {
    showApp();
  }
});
