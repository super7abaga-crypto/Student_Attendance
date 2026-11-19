/*
 * Engineer A — Learn2Earn Student Portal
 * ---------------------------------------------------------------------------
 * Frontend only. Every attendance decision (QR validity, session state, geofence,
 * duplicate protection, On Time / Late) belongs to Engineer B's Django backend.
 * This file displays what the API returns and never re-derives it.
 *
 * Auth: POST /auth/student/login/  ->  { token, student }
 *       Authorization: Token <token>  (never Bearer)
 */
const CONFIG = {
  // Same origin as the page by default, so Django can serve the portal at /student/
  // and the API at /api/v1/ without any edit. Override with the meta tag in index.html
  // or by setting window.LEARN2EARN_API_BASE before this script loads.
  API_BASE_URL: (() => {
    const meta = document.querySelector('meta[name="learn2earn-api-base"]');
    const override = String(window.LEARN2EARN_API_BASE || meta?.content || "").trim();
    if (override) return override.replace(/\/+$/, "");
    const { protocol, origin } = window.location;
    if (protocol === "http:" || protocol === "https:") return `${origin}/api/v1`;
    return "https://fellowship.learn2earn.ng/api/v1";
  })(),
  // The student portal never registers accounts; a mentor or administrator enrolls students.
  SESSION_STORAGE_KEY: "learn2earn.student.session",
  SESSION_HOURS: 12,
  WAT_TIMEZONE: "Africa/Lagos",
  // A fresh fix for every scan: no cached coordinates, high accuracy requested.
  GPS_OPTIONS: { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
  RECENT_ROWS: 5,
};

const SESSION_LABELS = {
  morning: "Morning Session",
  afternoon: "Afternoon Session",
  evening: "Evening Session",
};

// Known backend status values are humanised for the badge; anything else is shown raw.
const STATUS_LABELS = {
  on_time: "On Time",
  present: "Present",
  late: "Late",
  absent: "Absent",
};

const state = {
  token: null,
  student: null,
  records: [],
  historyMonth: "",
  dashboardMonth: "",
  scanner: null,
  scannerRunning: false,
  currentView: "dashboard",
  scanLocked: false,
  historyLoaded: false,
};

const $ = (id) => document.getElementById(id);
const apiUrl = (path) => `${CONFIG.API_BASE_URL}${path}`;

/* ------------------------------------------------------------------ utils -- */
function normalizeUsername(value) {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, "");
}

function sessionLabel(type) {
  const key = String(type || "").trim().toLowerCase();
  if (!key) return "—";
  return SESSION_LABELS[key] || key.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function statusLabel(status) {
  const key = String(status || "").trim().toLowerCase();
  if (!key) return "—";
  return STATUS_LABELS[key] || key.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Badge colour only. The text always comes from the backend; an unrecognised status
// must not be dressed up as a good one, so it gets a neutral grey instead.
const ON_TIME_ALIASES = ["present", "on_time", "on-time", "ontime"];

function statusClass(status) {
  const key = String(status || "").trim().toLowerCase();
  if (key === "late") return "late";
  if (key === "absent") return "absent";
  if (ON_TIME_ALIASES.includes(key)) return "on-time";
  return "neutral";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function watMonthKey(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: CONFIG.WAT_TIMEZONE, year: "numeric", month: "2-digit",
  }).formatToParts(date).reduce((acc, p) => (acc[p.type] = p.value, acc), {});
  return `${parts.year}-${parts.month}`;
}

function monthKeyOf(record) {
  const raw = String(record.attendance_date || record.scan_date || record.date || "");
  const match = /^(\d{4})-(\d{2})/.exec(raw);
  if (match) return `${match[1]}-${match[2]}`;
  const stamp = record.scanned_at || record.scan_time_wat || "";
  const parsed = Date.parse(stamp);
  if (!Number.isNaN(parsed)) return watMonthKey(new Date(parsed));
  return "";
}

function dateLabel(record) {
  const raw = String(record.attendance_date || record.scan_date || "").slice(0, 10);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (!match) return raw || "—";
  const date = new Date(`${raw}T12:00:00Z`);
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: CONFIG.WAT_TIMEZONE, day: "2-digit", month: "short", year: "numeric",
  }).format(date);
}

function timeLabel(record) {
  // The backend sends scan_time_wat (already WAT). Use it verbatim when present.
  const wat = String(record.scan_time_wat || "").trim();
  if (wat) return wat.length > 5 ? wat.slice(0, 5) : wat;
  const stamp = record.scanned_at || record.timestamp || "";
  const parsed = Date.parse(stamp);
  if (Number.isNaN(parsed)) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: CONFIG.WAT_TIMEZONE, hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(parsed));
}

function statusBadge(record) {
  const raw = String(record.status || "").trim();
  return `<span class="status-pill ${statusClass(raw)}" data-status="${escapeHtml(raw)}">${escapeHtml(statusLabel(raw))}</span>`;
}

function showToast(message) {
  const toast = $("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 4200);
}

/* ------------------------------------------------------------------- auth -- */
function normaliseStudent(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  const campusValue = source.campus ?? source.campus_name ?? source.campus_name_display ?? null;
  let campus = "";
  if (typeof campusValue === "string") campus = campusValue;
  else if (campusValue && typeof campusValue === "object") campus = campusValue.name || campusValue.code || campusValue.title || "";
  const fullName = source.full_name
    || source.name
    || [source.first_name, source.last_name].filter(Boolean).join(" ")
    || source.username
    || "Student";
  return {
    id: source.id ?? source.student_id ?? source.pk ?? null,
    full_name: String(fullName),
    username: String(source.username || source.user_name || ""),
    campus: String(campus || ""),
  };
}

function extractToken(body) {
  if (!body || typeof body !== "object") return null;
  return body.token || body.access_token || body.key || body.auth_token || null;
}

function saveSession() {
  try {
    window.sessionStorage.setItem(CONFIG.SESSION_STORAGE_KEY, JSON.stringify({
      token: state.token,
      student: state.student,
      savedAt: Date.now(),
    }));
  } catch { /* storage disabled: the session simply will not survive a refresh */ }
}

function clearSession() {
  state.token = null;
  state.student = null;
  state.records = [];
  state.historyLoaded = false;
  try { window.sessionStorage.removeItem(CONFIG.SESSION_STORAGE_KEY); } catch { /* ignore */ }
}

function restoreSession() {
  let saved;
  try { saved = JSON.parse(window.sessionStorage.getItem(CONFIG.SESSION_STORAGE_KEY) || "null"); }
  catch { return false; }
  if (!saved || !saved.token || !saved.student) return false;
  const ageMs = Date.now() - Number(saved.savedAt || 0);
  if (!Number.isFinite(ageMs) || ageMs > CONFIG.SESSION_HOURS * 3600 * 1000) {
    clearSession();
    return false;
  }
  state.token = saved.token;
  state.student = normaliseStudent(saved.student);
  return true;
}

class ApiError extends Error {
  constructor(message, { status = 0, body = null, code = "" } = {}) {
    super(message);
    this.status = status;
    this.body = body;
    this.code = code;
  }
}

function errorCode(body) {
  if (!body || typeof body !== "object") return "";
  return String(body.code || body.error_code || body.error || body.reason || "").trim().toLowerCase();
}

async function apiRequest(path, { method = "GET", body, auth = true } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && state.token) headers.Authorization = `Token ${state.token}`;

  let response;
  try {
    response = await fetch(apiUrl(path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Cannot reach the attendance server. Check your connection and try again.", { status: 0 });
  }

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const detail = payload && (payload.detail || payload.message || payload.error_description);
    const safeMessage = typeof detail === "string" && detail.trim()
      ? detail.trim()
      : defaultMessageForStatus(response.status);
    const error = new ApiError(safeMessage, {
      status: response.status,
      body: payload,
      code: errorCode(payload),
    });
    if (response.status === 401 && state.token) {
      clearSession();
      error.sessionExpired = true;
    }
    throw error;
  }
  return payload;
}

function defaultMessageForStatus(status) {
  if (status === 400) return "We could not process that request. Check your details and try again.";
  if (status === 401) return "Your sign-in is no longer valid. Please sign in again.";
  if (status === 403) return "You are not allowed to do that. Contact your mentor if it continues.";
  if (status === 404) return "That service is not available right now. Contact your mentor.";
  if (status === 409) return "That record already exists.";
  if (status === 429) return "Too many attempts. Wait a moment and try again.";
  if (status >= 500) return "The attendance server had a problem. Please try again shortly.";
  return "The request could not be completed.";
}

function clearAuthAlert() {
  const alert = $("authAlert");
  if (!alert) return;
  alert.textContent = "";
  alert.classList.add("hidden");
}

function showAuthAlert(message) {
  const alert = $("authAlert");
  if (!alert) return;
  alert.textContent = message;
  alert.classList.remove("hidden");
}

function handleSessionExpired() {
  clearSession();
  showAuth();
  showAuthAlert("Your session ended. Please sign in again.");
}

async function handleLogin(event) {
  event.preventDefault();
  clearAuthAlert();
  const username = normalizeUsername($("loginUsername").value);
  const password = $("loginPassword").value;
  if (!username || !password) {
    showAuthAlert("Enter your attendance username and password.");
    return;
  }
  const button = $("loginFormEl").querySelector("button[type=submit]");
  const original = button.innerHTML;
  button.disabled = true;
  button.textContent = "Signing in…";
  try {
    const body = await apiRequest("/auth/student/login/", {
      method: "POST",
      auth: false,
      body: { username, password },
    });
    const token = extractToken(body);
    if (!token) throw new ApiError("The server did not return a login token. Contact your mentor.", { status: 0 });
    state.token = token;
    state.student = normaliseStudent(body.student || body.user || body.profile || body);
    saveSession();
    $("loginPassword").value = "";
    showApp();
  } catch (error) {
    if (error.status === 401 || error.status === 400) {
      showAuthAlert(error.message || "Incorrect username or password.");
    } else {
      showAuthAlert(error.message);
    }
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

async function handleLogout() {
  try {
    if (state.token) await apiRequest("/auth/logout/", { method: "POST", body: {} });
  } catch { /* the local session is cleared regardless of the server response */ }
  clearSession();
  showAuth();
  showToast("You have signed out.");
}

/* ------------------------------------------------------------------- view -- */
function showApp() {
  $("authScreen").classList.add("hidden");
  $("topName").textContent = state.student.full_name;
  $("topUsername").textContent = state.student.username ? `@${state.student.username}` : "";
  $("topCampus").textContent = state.student.campus || "";
  $("topAvatar").textContent = String(state.student.full_name || "?").trim().charAt(0).toUpperCase();
  $("welcomeName").textContent = String(state.student.full_name || "").split(" ")[0] || "Student";
  $("profileName").textContent = state.student.full_name || "—";
  $("profileUsername").textContent = state.student.username || "—";
  $("profileCampus").textContent = state.student.campus || "Not assigned";
  showView("dashboard");
  loadAttendance();
}

function showAuth() {
  stopScanner();
  $("authScreen").classList.remove("hidden");
}

function showView(name) {
  if (!$(`${name}View`)) name = "dashboard";
  state.currentView = name;
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  $(`${name}View`).classList.add("active");
  document.querySelectorAll(".nav-item[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $("pageTitle").textContent = ({ dashboard: "Dashboard", scanner: "Scan attendance", history: "Attendance history" })[name] || "Dashboard";
  $("sidebar").classList.remove("open");
  if (name !== "scanner") stopScanner();
  if (name === "history" && state.student) loadAttendance();
}

/* -------------------------------------------------------------- attendance -- */
function setTableState(tbody, message, kind = "empty") {
  tbody.innerHTML = `<tr><td colspan="4" class="empty-cell ${kind}">${escapeHtml(message)}</td></tr>`;
}

function recordRow(record) {
  return `<tr>
    <td data-label="Session"><strong>${escapeHtml(sessionLabel(record.session_type || record.session_name))}</strong></td>
    <td data-label="Date">${escapeHtml(dateLabel(record))}</td>
    <td data-label="Time">${escapeHtml(timeLabel(record))}</td>
    <td data-label="Status">${statusBadge(record)}</td>
  </tr>`;
}

function sortRecords(records) {
  return [...records].sort((a, b) => {
    const aKey = `${a.attendance_date || ""}T${a.scan_time_wat || a.scanned_at || ""}`;
    const bKey = `${b.attendance_date || ""}T${b.scan_time_wat || b.scanned_at || ""}`;
    return bKey.localeCompare(aKey);
  });
}

function renderDashboard() {
  const month = watMonthKey();
  const records = sortRecords(state.records.filter((r) => monthKeyOf(r) === month));
  const onTime = records.filter((r) => statusClass(r.status) === "on-time").length;
  const late = records.filter((r) => statusClass(r.status) === "late").length;

  $("statAttended").textContent = String(records.length);
  $("statOnTime").textContent = String(onTime);
  $("statLate").textContent = String(late);

  if (records.length) {
    const latest = records[0];
    $("statLast").textContent = timeLabel(latest);
    $("statLastMeta").textContent = `${sessionLabel(latest.session_type || latest.session_name)} · ${dateLabel(latest)}`;
  } else {
    $("statLast").textContent = "—";
    $("statLastMeta").textContent = "No scan recorded yet";
  }

  const tbody = $("recentRows");
  if (!records.length) {
    setTableState(tbody, "No attendance recorded this month yet.");
    return;
  }
  tbody.innerHTML = records.slice(0, CONFIG.RECENT_ROWS).map(recordRow).join("");
}

function renderHistory() {
  const month = state.historyMonth || watMonthKey();
  const records = sortRecords(state.records.filter((r) => monthKeyOf(r) === month));
  const tbody = $("historyRows");
  const count = $("historyCount");

  if (!state.historyLoaded) {
    setTableState(tbody, "Loading your attendance…");
    count.textContent = "—";
    return;
  }
  if (!records.length) {
    setTableState(tbody, `No attendance recorded for ${month}.`);
    count.textContent = "0 records";
    return;
  }
  tbody.innerHTML = records.map(recordRow).join("");
  count.textContent = `${records.length} record${records.length === 1 ? "" : "s"}`;
}

async function loadAttendance() {
  if (!state.token) return;
  if (!state.historyLoaded) {
    setTableState($("historyRows"), "Loading your attendance…");
    setTableState($("recentRows"), "Loading your attendance…");
  }
  try {
    const payload = await apiRequest("/student/attendance-history/");
    // The contract returns a bare list; tolerate a wrapped list defensively.
    const list = Array.isArray(payload)
      ? payload
      : Array.isArray(payload?.records) ? payload.records
      : Array.isArray(payload?.results) ? payload.results
      : [];
    state.records = list;
    state.historyLoaded = true;
    renderDashboard();
    renderHistory();
  } catch (error) {
    if (error.sessionExpired) return handleSessionExpired();
    state.historyLoaded = true;
    setTableState($("historyRows"), error.message, "error");
    setTableState($("recentRows"), error.message, "error");
    $("historyCount").textContent = "Could not load records";
    showToast(error.message);
  }
}

/* ----------------------------------------------------------------- scanner -- */
function setScanState(visible, title, text) {
  const box = $("scanState");
  if (!box) return;
  if (!visible) { box.classList.add("hidden"); return; }
  $("scanStateTitle").textContent = title;
  $("scanStateText").textContent = text || "";
  box.classList.remove("hidden");
}

function showScanNotice(message, { retry = false } = {}) {
  const notice = $("scanNotice");
  notice.textContent = message;
  notice.classList.remove("hidden");
  $("scanRetry").classList.toggle("hidden", !retry);
}

function clearScanNotice() {
  $("scanNotice").classList.add("hidden");
  $("scanRetry").classList.add("hidden");
}

async function startScanner() {
  clearScanNotice();
  const notice = $("scanNotice");
  if (!window.Html5Qrcode) {
    showScanNotice("The QR scanner library did not load. Check your internet connection and refresh the page.", { retry: true });
    return;
  }
  if (state.scanLocked) {
    showScanNotice("Your previous scan is still being verified. Please wait.");
    return;
  }
  if (state.scannerRunning) return;
  try {
    if (!state.scanner) state.scanner = new window.Html5Qrcode("reader");
    const cameras = await window.Html5Qrcode.getCameras();
    if (!cameras || !cameras.length) throw new Error("No camera was found on this device.");
    const camera = cameras.find((c) => /back|rear|environment/i.test(c.label || "")) || cameras[cameras.length - 1];
    await state.scanner.start(
      camera.id,
      { fps: 10, qrbox: { width: 230, height: 230 }, aspectRatio: 1.0 },
      onQrDecoded,
      () => {},
    );
    state.scannerRunning = true;
    $("startScanBtn").disabled = true;
    $("stopScanBtn").disabled = false;
    notice.classList.add("hidden");
  } catch (error) {
    showScanNotice(
      error?.message || "Could not start the camera. Allow camera access and use HTTPS, then try again.",
      { retry: true },
    );
  }
}

async function stopScanner() {
  if (!state.scanner || !state.scannerRunning) return;
  try { await state.scanner.stop(); } catch { /* already stopped */ }
  try { state.scanner.clear(); } catch { /* older builds */ }
  state.scannerRunning = false;
  const start = $("startScanBtn");
  const stop = $("stopScanBtn");
  if (start) start.disabled = false;
  if (stop) stop.disabled = true;
}

function geolocationError(error) {
  const code = error && typeof error === "object" ? error.code : 0;
  if (code === 1) {
    return new ApiError(
      "Location permission is required to check in. Allow location access for this site, then scan again.",
      { code: "gps_permission_denied" },
    );
  }
  if (code === 2) {
    return new ApiError(
      "Your location is unavailable right now. Move to an open area with a clearer signal and try again.",
      { code: "gps_unavailable" },
    );
  }
  if (code === 3) {
    return new ApiError("Getting your location took too long. Try again.", { code: "gps_timeout" });
  }
  return new ApiError("We could not read your location. Check that location services are on and try again.", { code: "gps_error" });
}

function getFreshPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new ApiError(
        "This browser cannot share your location, so attendance cannot be verified. Try a phone or a browser with location support.",
        { code: "gps_unsupported" },
      ));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => resolve({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy,
      }),
      (error) => reject(geolocationError(error)),
      CONFIG.GPS_OPTIONS,
    );
  });
}

function describeScanError(error) {
  const code = String(error.code || "").toLowerCase();
  const message = String(error.message || "").trim();
  const body = error.body && typeof error.body === "object" ? error.body : {};

  if (error.status === 409 || code.includes("duplicate")) {
    return { text: "Already checked in for this session.", duplicate: true };
  }
  if (code.includes("expired") || /expired/i.test(message)) {
    return { text: "This QR code has expired. Ask your mentor to show the current code and scan again.", retry: true };
  }
  if (code.includes("invalid") && code.includes("qr") || /not a valid qr|invalid qr|malformed/i.test(message)) {
    return { text: "That QR code was not recognised. Make sure you are scanning the attendance code, not another QR code.", retry: true };
  }
  if (code.includes("campus") || code.includes("geofence") || code.includes("distance") || code.includes("location")) {
    return { text: message || "You appear to be outside your campus. Move closer to the campus and scan again.", retry: true };
  }
  if (code.includes("inactive") || code.includes("no_session") || code.includes("closed")) {
    return { text: message || "There is no active attendance session right now. Ask your mentor when the next session opens.", retry: true };
  }
  if (code.includes("accuracy")) {
    return { text: message || "Your location was not accurate enough to verify attendance. Move to an open area and try again.", retry: true };
  }
  if (error.status === 401) {
    return { text: "Your session ended. Please sign in again." };
  }
  if (error.status === 403) {
    return { text: message || "The server rejected this scan. Contact your mentor if it keeps happening.", retry: true };
  }
  if (error.status === 429) {
    return { text: "Too many scans in a short time. Wait a moment and try again.", retry: true };
  }
  if (error.status >= 500) {
    return { text: "The attendance server had a problem recording your scan. Please try again shortly.", retry: true };
  }
  if (body.detail && typeof body.detail === "string") {
    return { text: body.detail, retry: true };
  }
  return { text: message || "We could not record your attendance. Please try again.", retry: true };
}

async function onQrDecoded(decodedText) {
  if (state.scanLocked) return;                 // one submission at a time
  state.scanLocked = true;
  clearScanNotice();
  $("startScanBtn").disabled = true;
  $("stopScanBtn").disabled = true;

  // The decoded text is sent exactly as the camera produced it; only the server judges it.
  const qrPayload = decodedText;

  try {
    setScanState(true, "Verifying scan…", "Getting your location…");
    await stopScanner();
    const position = await getFreshPosition();

    setScanState(true, "Verifying scan…", "Checking your QR code and location with the attendance server.");
    const result = await apiRequest("/attendance/scan/", {
      method: "POST",
      body: {
        qr_payload: qrPayload,
        latitude: position.latitude,
        longitude: position.longitude,
        accuracy: position.accuracy,
      },
    });

    const attendance = result && (result.attendance || result.record) ? (result.attendance || result.record) : result;
    setScanState(false);
    showConfirmation(attendance || {}, { duplicate: false });
    await loadAttendance();
  } catch (error) {
    setScanState(false);
    if (error.sessionExpired) return handleSessionExpired();

    const described = describeScanError(error);
    if (described.duplicate) {
      const existing = (error.body && (error.body.attendance || error.body.record)) || null;
      if (existing) {
        // Keep the original attendance visible instead of replacing it with an empty card.
        showConfirmation(existing, { duplicate: true });
        showScanNotice("Already checked in for this session.");
      } else {
        showScanNotice("Already checked in for this session.");
      }
      return;
    }
    showScanNotice(described.text, { retry: described.retry !== false });
    showToast(described.text);
  } finally {
    state.scanLocked = false;
    $("startScanBtn").disabled = false;
    $("stopScanBtn").disabled = true;
  }
}

/* ------------------------------------------------------------ confirmation -- */
function showConfirmation(attendance, { duplicate = false } = {}) {
  const rawStatus = String(attendance.status || "").trim();
  $("confirmName").textContent = attendance.full_name || state.student?.full_name || "—";
  $("confirmUsername").textContent = attendance.username || state.student?.username || "—";
  $("confirmSession").textContent = sessionLabel(attendance.session_type || attendance.session_name);
  $("confirmDate").textContent = attendance.attendance_date ? dateLabel(attendance) : "—";
  $("confirmTime").textContent = timeLabel(attendance);

  // attendance_action is returned by the backend; we display it verbatim and never
  // branch on its value (Engineer B owns the enum).
  const rawAction = String(attendance.attendance_action || "").trim();
  $("confirmActionRow").classList.toggle("hidden", !rawAction);
  $("confirmAction").textContent = rawAction || "—";
  $("confirmAction").dataset.action = rawAction;

  const statusEl = $("confirmStatus");
  statusEl.dataset.status = rawStatus;
  statusEl.textContent = rawStatus ? statusLabel(rawStatus).toUpperCase() : "RECORDED";
  statusEl.className = `confirmation-status ${statusClass(rawStatus)}`;

  const card = $("confirmationModal").querySelector(".confirmation-card");
  card.classList.toggle("duplicate", duplicate);
  $("confirmationMark").textContent = duplicate ? "!" : "✓";
  $("confirmationEyebrow").textContent = duplicate ? "ALREADY RECORDED" : "ATTENDANCE VERIFIED";
  $("confirmationTitle").textContent = duplicate ? "Already checked in" : "You're checked in!";
  $("confirmationSubtitle").textContent = duplicate
    ? "Already checked in for this session. This is the record we already have for you."
    : "Your attendance has been recorded successfully.";

  $("confirmationModal").classList.remove("hidden");
  $("confirmationModal").querySelector(".confirmation-card").focus();
}

function hideConfirmation() {
  $("confirmationModal").classList.add("hidden");
}

/* ------------------------------------------------------------------- wiring */
function setConnectionNote() {
  const note = $("connectionNote");
  if (!note) return;
  note.textContent = `Attendance service: ${CONFIG.API_BASE_URL}`;
}

function wireEvents() {
  $("loginFormEl").addEventListener("submit", handleLogin);
  $("logoutBtn").addEventListener("click", handleLogout);
  $("dashboardScanBtn").addEventListener("click", () => showView("scanner"));
  $("startScanBtn").addEventListener("click", startScanner);
  $("stopScanBtn").addEventListener("click", stopScanner);
  $("retryScanBtn").addEventListener("click", () => { clearScanNotice(); startScanner(); });
  $("retryCameraBtn").addEventListener("click", async () => { clearScanNotice(); await stopScanner(); startScanner(); });
  $("menuBtn").addEventListener("click", () => $("sidebar").classList.toggle("open"));
  $("closeConfirmation").addEventListener("click", hideConfirmation);
  $("confirmationModal").addEventListener("click", (event) => {
    if (event.target === $("confirmationModal")) hideConfirmation();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("confirmationModal").classList.contains("hidden")) hideConfirmation();
  });
  document.querySelectorAll(".nav-item[data-view]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
  document.querySelectorAll("[data-go]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.go));
  });
  $("monthFilter").addEventListener("change", () => {
    state.historyMonth = $("monthFilter").value || watMonthKey();
    renderHistory();
  });
}

function init() {
  $("year").textContent = String(new Date().getFullYear());
  state.dashboardMonth = watMonthKey();
  state.historyMonth = state.dashboardMonth;
  $("monthFilter").value = state.dashboardMonth;
  setConnectionNote();
  wireEvents();
  if (restoreSession()) showApp();
  else showAuth();
}

document.addEventListener("DOMContentLoaded", init);
