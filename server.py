#!/usr/bin/env python3
"""
Engineer A - local development backend (NOT for production)
----------------------------------------------------------------
A zero-dependency Python server (standard library only) that implements exactly the
endpoints in API_CONTRACT.md, so the student portal can be run and demoed before
Engineer B's real backend is ready.

    python server.py            -> http://localhost:8000

It also serves the frontend from this folder, so opening http://localhost:8000 gives
you the portal talking to this API (camera scanning works on localhost without HTTPS).

What this server does that a real backend must do properly:
  - validates and normalises usernames, enforces uniqueness
  - hashes passwords (scrypt + per-user salt), never stores plaintext
  - signs access tokens and verifies them per request
  - derives the student from the token, never from the request body
  - signs the QR payload (ATTv1) and checks signature, expiry and scan date
  - decides On Time / Late from the server clock in Africa/Lagos (WAT)
  - enforces one attendance row per student per session

Data lives in memory and is mirrored to dev/.data.json (git-ignored).
Delete that file to start from a clean state.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
DEV_DIR = ROOT / "dev"
DATA_FILE = DEV_DIR / ".data.json"

PORT = int(os.environ.get("PORT") or 8000)
HOST = os.environ.get("HOST") or "0.0.0.0"

APP_SECRET = (os.environ.get("APP_SECRET") or secrets.token_hex(32)).encode()
QR_SECRET = (os.environ.get("QR_SECRET") or secrets.token_hex(32)).encode()
TOKEN_TTL_MS = 2 * 60 * 60 * 1000
QR_TTL_MS = 2 * 60 * 1000
# Engineer B signs their kiosk codes with a secret this dev server does not hold, so
# their QR can never verify here. Set ALLOW_FOREIGN_QR=1 to accept a well-formed code
# from their kiosk for local integration testing. Never enable it for real attendance.
ALLOW_FOREIGN_QR = (os.environ.get("ALLOW_FOREIGN_QR") or "").lower() in ("1", "true", "yes")

DB_LOCK = threading.Lock()

# ------------------------------------------------------------------ time ---
# Africa/Lagos is UTC+1 all year (no daylight saving).
WAT_OFFSET = timedelta(minutes=60)


def wat_parts(moment: datetime | None = None) -> dict:
    moment = moment or datetime.now(timezone.utc)
    shifted = moment.astimezone(timezone.utc) + WAT_OFFSET
    return {
        "date": shifted.strftime("%Y-%m-%d"),   # YYYY-MM-DD in WAT
        "month": shifted.strftime("%Y-%m"),     # YYYY-MM in WAT
        "minutes": shifted.hour * 60 + shifted.minute,
    }


def iso_ms(moment: datetime) -> str:
    """Same shape as JavaScript's Date.toISOString(): 2026-11-18T14:25:07.745Z"""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


# Session windows, WAT. A scan is on time from the moment the mentor's QR is generated
# until the cutoff minute inclusive; anything after the cutoff is late.
#   Morning   09:00 - 09:10
#   Afternoon 13:00 - 13:10
#   Evening   17:00 - 17:15
SESSIONS = {
    "morning": {"label": "Morning session", "start": 9 * 60, "cutoff": 9 * 60 + 10},
    "afternoon": {"label": "Afternoon session", "start": 13 * 60, "cutoff": 13 * 60 + 10},
    "evening": {"label": "Evening session", "start": 17 * 60, "cutoff": 17 * 60 + 15},
}
SESSION_ORDER = ["morning", "afternoon", "evening"]


def active_session(moment: datetime | None = None) -> str:
    minutes = wat_parts(moment)["minutes"]
    for key in SESSION_ORDER:
        if SESSIONS[key]["start"] <= minutes < SESSIONS[key]["start"] + 180:
            return key
    for key in SESSION_ORDER:
        if minutes < SESSIONS[key]["start"]:
            return key
    return "evening"


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ------------------------------------------------------------------ data ---
db = {"students": [], "attendance": []}


def load_data() -> None:
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if isinstance(raw.get("students"), list):
            db["students"] = raw["students"]
        if isinstance(raw.get("attendance"), list):
            db["attendance"] = raw["attendance"]
    except Exception:
        pass


def save_data() -> None:
    try:
        DEV_DIR.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(db, indent=2), encoding="utf-8")
    except Exception:
        pass


# ------------------------------------------------------------- passwords ---
def hash_password(password: str, salt: str | None = None) -> dict:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
    return {"salt": salt, "hash": digest.hex()}


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    candidate = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
    return hmac.compare_digest(candidate.hex(), expected_hash)


# ---------------------------------------------------------------- tokens ---
def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(value: str, secret: bytes | None = None) -> str:
    key = APP_SECRET if secret is None else secret
    return b64url(hmac.new(key, value.encode(), hashlib.sha256).digest())


def issue_token(student_id: str) -> str:
    payload = b64url(json.dumps({"sub": student_id, "exp": now_ms() + TOKEN_TTL_MS}).encode())
    return f"{payload}.{sign(payload)}"


def read_token(token: str | None) -> dict | None:
    if not isinstance(token, str) or "." not in token:
        return None
    payload, _, signature = token.partition(".")
    if not hmac.compare_digest(sign(payload), signature):
        return None
    try:
        data = json.loads(unb64url(payload))
    except Exception:
        return None
    if not data.get("exp") or data["exp"] < now_ms():
        return None
    return data


def authed_student(headers) -> dict | None:
    header = headers.get("Authorization") or ""
    token = header[7:].strip() if header.startswith("Bearer ") else None
    claims = read_token(token)
    if not claims:
        return None
    return next((s for s in db["students"] if s["id"] == claims.get("sub")), None)


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


# -------------------------------------------------------------------- QR ---
def issue_qr(session_key: str, scan_date: str | None = None) -> dict:
    payload = {
        "session": session_key,
        "token": secrets.token_hex(12),
        "expiresAt": now_ms() + QR_TTL_MS,
        "scanDate": scan_date or wat_parts()["date"],
    }
    body = b64url(json.dumps(payload).encode())
    return {"qr_payload": f"ATTv1.{body}.{sign(body, QR_SECRET)}", "payload": payload}


def normalize_foreign_payload(raw) -> dict:
    """Tolerate the field names Engineer B's kiosk may use, so an unverified code still
    maps onto this server's session table instead of failing on a naming difference."""
    source = raw if isinstance(raw, dict) else {}
    session_key = str(
        source.get("session") or source.get("session_type") or source.get("sessionType") or ""
    ).strip().lower()
    if session_key in SESSIONS:
        session = session_key
    else:
        session = next((k for k in SESSION_ORDER if k.startswith(session_key[:3])), session_key) if session_key else session_key

    expires_at = source.get("expiresAt", source.get("expires_at", source.get("exp")))
    if isinstance(expires_at, str):
        if re.fullmatch(r"\d+", expires_at):
            expires_at = int(expires_at)
        else:
            try:
                expires_at = int(datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp() * 1000)
            except Exception:
                expires_at = None
    if isinstance(expires_at, (int, float)) and expires_at < 1e12:
        expires_at = int(expires_at * 1000)

    scan_date = source.get("scanDate") or source.get("scan_date") or wat_parts()["date"]
    return {
        "session": session,
        "token": source.get("token") or source.get("qr_token"),
        "expiresAt": expires_at,
        "scanDate": scan_date,
    }


def verify_qr(qr_payload) -> dict:
    if not isinstance(qr_payload, str):
        return {"error": "Invalid QR code."}
    match = re.fullmatch(r"ATTv1\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)", qr_payload.strip())
    if not match:
        return {"error": "This is not an attendance QR code."}
    body, signature = match.group(1), match.group(2)
    try:
        payload = json.loads(unb64url(body))
    except Exception:
        return {"error": "This QR code is damaged. Ask your mentor to show a fresh one."}

    if not hmac.compare_digest(sign(body, QR_SECRET), signature):
        # Codes from Engineer B's kiosk carry their own signature. The real check happens
        # on their server; this stand-in can only accept them when explicitly told to.
        if not ALLOW_FOREIGN_QR:
            return {"error": "This QR code was not issued by the attendance system."}
        payload = normalize_foreign_payload(payload)
        print("[dev] accepted a QR payload signed by another issuer (ALLOW_FOREIGN_QR=1)", flush=True)

    if payload.get("session") not in SESSIONS:
        return {"error": "Unknown attendance session."}
    expires_at = payload.get("expiresAt")
    if not expires_at or expires_at < now_ms():
        return {"error": "This QR code has expired. Scan the current one."}
    if payload.get("scanDate") != wat_parts()["date"]:
        return {"error": "This QR code is for a different day."}
    return {"payload": payload}


# --------------------------------------------------------------- helpers ---
def public_student(student: dict) -> dict:
    return {"id": student["id"], "full_name": student["full_name"], "username": student["username"]}


def attendance_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "session_name": row["session_name"],
        "attended_at": row["attended_at"],
        "status": row["status"],
    }


MIME_OVERRIDES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".md": "text/markdown; charset=utf-8",
    ".woff2": "font/woff2",
}


# --------------------------------------------------------------- handler ---
class Handler(BaseHTTPRequestHandler):
    server_version = "Learn2EarnDev/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the terminal readable
        pass

    # -- plumbing --
    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "600")

    def send_json(self, status: int, body) -> None:
        raw = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.cors()
        self.end_headers()
        self.wfile.write(raw)

    def drain_body(self) -> None:
        """Read the request body once, whatever the route decides to do with it.
        Skipping this on an early return (401, 404) leaves bytes in the socket and the
        next keep-alive request is parsed as garbage."""
        length = int(self.headers.get("Content-Length") or 0)
        self.raw_body = b""
        if length <= 0:
            return
        if length > 1_000_000:
            raise ValueError("Payload too large")
        self.raw_body = self.rfile.read(length)

    def read_json(self) -> dict:
        raw = getattr(self, "raw_body", b"")
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            raise ValueError("Invalid JSON body")
        return data if isinstance(data, dict) else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method: str):
        parsed = urlparse(self.path)
        try:
            self.drain_body()
        except ValueError as error:
            return self.send_json(413, {"detail": str(error)})
        if parsed.path.startswith("/api/v1"):
            try:
                self.handle_api(method, parsed)
            except ValueError as error:
                self.send_json(400, {"detail": str(error) or "Bad request"})
            except Exception as error:  # never leak a stack trace to the portal
                self.send_json(400, {"detail": str(error) or "Bad request"})
            return
        self.serve_static(unquote(parsed.path))

    # -- API --
    def handle_api(self, method: str, parsed) -> None:
        route = re.sub(r"^/api/v1", "", parsed.path)
        query = parse_qs(parsed.query)
        first = lambda name: (query.get(name) or [None])[0]

        if route == "/auth/register" and method == "POST":
            return self.register()
        if route == "/auth/login" and method == "POST":
            return self.login()
        if route == "/auth/logout" and method == "POST":
            return self.send_json(200, {"ok": True})
        if route == "/students/me/attendance" and method == "GET":
            return self.attendance(first("month"))
        if route == "/attendance/check-in" and method == "POST":
            return self.check_in()
        if route == "/dev/qr" and method == "GET":
            return self.dev_qr(first("session"))
        if route == "/dev/reset" and method == "POST":
            return self.dev_reset()
        return self.send_json(404, {"detail": f"No route for {method} {parsed.path}"})

    def register(self):
        body = self.read_json()
        full_name = re.sub(r"\s+", " ", str(body.get("full_name") or "")).strip()
        username = re.sub(r"\s+", "", str(body.get("username") or "").lower())
        password = str(body.get("password") or "")
        if len(full_name) < 2:
            return self.send_json(422, {"detail": "Enter your full name."})
        if not re.fullmatch(r"[a-z0-9_-]{3,30}", username):
            return self.send_json(422, {"detail": "Username must be 3-30 characters: lowercase letters, numbers, _ or -."})
        if len(password) < 8:
            return self.send_json(422, {"detail": "Password must be at least 8 characters."})
        with DB_LOCK:
            if any(s["username"] == username for s in db["students"]):
                return self.send_json(409, {"detail": "That username is already taken."})
            salted = hash_password(password)
            student = {
                "id": str(uuid.uuid4()),
                "full_name": full_name,
                "username": username,
                "password_salt": salted["salt"],
                "password_hash": salted["hash"],
                "track": body.get("track") or "General",
                "created_at": iso_ms(datetime.now(timezone.utc)),
            }
            db["students"].append(student)
            save_data()
        return self.send_json(201, {
            "access_token": issue_token(student["id"]),
            "token_type": "bearer",
            "student": public_student(student),
        })

    def login(self):
        body = self.read_json()
        username = re.sub(r"\s+", "", str(body.get("username") or "").lower())
        password = str(body.get("password") or "")
        student = next((s for s in db["students"] if s["username"] == username), None)
        if not student or not verify_password(password, student["password_salt"], student["password_hash"]):
            return self.send_json(401, {"detail": "Incorrect username or password."})
        return self.send_json(200, {
            "access_token": issue_token(student["id"]),
            "token_type": "bearer",
            "student": public_student(student),
        })

    def attendance(self, month: str | None):
        student = authed_student(self.headers)
        if not student:
            return self.send_json(401, {"detail": "Your session has expired. Please sign in again."})
        month = month or wat_parts()["month"]
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            return self.send_json(422, {"detail": "month must look like 2026-11"})
        rows = [a for a in db["attendance"] if a.get("student_id") == student["id"] and a.get("month") == month]
        rows.sort(key=lambda a: str(a.get("attended_at")), reverse=True)
        total_sessions = 15 if month == wat_parts()["month"] else 20  # illustrative denominator
        return self.send_json(200, {"records": [attendance_view(r) for r in rows], "total_sessions": total_sessions})

    def check_in(self):
        student = authed_student(self.headers)
        if not student:
            return self.send_json(401, {"detail": "Your session has expired. Please sign in again."})
        body = self.read_json()
        verified = verify_qr(body.get("qr_payload"))
        if "error" in verified:
            return self.send_json(400, {"detail": verified["error"]})

        payload = verified["payload"]
        session = SESSIONS[payload["session"]]
        session_id = f"{payload['scanDate']}-{payload['session']}"
        with DB_LOCK:
            existing = next(
                (a for a in db["attendance"] if a["student_id"] == student["id"] and a["session_id"] == session_id),
                None,
            )
            if existing:
                return self.send_json(409, {
                    "detail": "Already checked in for this session.",
                    "code": "DUPLICATE_ATTENDANCE",
                    "already_checked_in": True,
                })

            moment = datetime.now(timezone.utc)
            wat = wat_parts(moment)
            status = "late" if wat["minutes"] > session["cutoff"] else "on_time"
            row = {
                "id": str(uuid.uuid4()),
                "student_id": student["id"],
                "session_id": session_id,
                "session_name": session["label"],
                "attended_at": iso_ms(moment),
                "status": status,
                "scan_date": wat["date"],
                "month": wat["month"],
            }
            db["attendance"].append(row)
            save_data()
        return self.send_json(201, {
            "attendance_id": row["id"],
            "student": public_student(student),
            "session_id": row["session_id"],
            "session_name": row["session_name"],
            "attended_at": row["attended_at"],
            "status": row["status"],
        })

    def dev_qr(self, requested: str | None):
        session_key = requested if requested in SESSIONS else active_session()
        issued = issue_qr(session_key)
        wat = wat_parts()
        expires = datetime.fromtimestamp(issued["payload"]["expiresAt"] / 1000, timezone.utc)
        return self.send_json(200, {
            "qr_payload": issued["qr_payload"],
            "session": session_key,
            "session_name": SESSIONS[session_key]["label"],
            "expires_at": iso_ms(expires),
            "scan_date": issued["payload"]["scanDate"],
            "server_time_wat": f"{wat['date']} {hhmm(wat['minutes'])}",
            "cutoff_wat": hhmm(SESSIONS[session_key]["cutoff"]),
        })

    def dev_reset(self):
        with DB_LOCK:
            db["students"] = []
            db["attendance"] = []
            save_data()
            seed()
        return self.send_json(200, {"ok": True, "students": len(db["students"])})

    # -- static --
    def serve_static(self, pathname: str):
        if pathname in ("", "/"):
            pathname = "/index.html"
        target = (ROOT / pathname.lstrip("/")).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            return self.send_text(403, "Forbidden")
        if not target.is_file():
            return self.send_text(404, "404 Not found")
        suffix = target.suffix.lower()
        content_type = MIME_OVERRIDES.get(suffix) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, status: int, text: str):
        raw = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


# ------------------------------------------------------------------ seed ---
def seed() -> None:
    if db["students"]:
        return
    demo = hash_password("demo12345")
    student = {
        "id": str(uuid.uuid4()),
        "full_name": "Demo Student",
        "username": "demo_student",
        "password_salt": demo["salt"],
        "password_hash": demo["hash"],
        "track": "General",
        "created_at": iso_ms(datetime.now(timezone.utc)),
    }
    db["students"].append(student)
    today = datetime.strptime(wat_parts()["date"], "%Y-%m-%d")
    month = wat_parts()["month"]
    for index, offset in enumerate([1, 2, 3]):
        scan_date = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        if scan_date[:7] != month:
            continue
        db["attendance"].append({
            "id": str(uuid.uuid4()),
            "student_id": student["id"],
            "session_id": f"{scan_date}-morning",
            "session_name": SESSIONS["morning"]["label"],
            "attended_at": f"{scan_date}T08:{'12' if index == 2 else '04'}:00.000Z",
            "status": "late" if index == 2 else "on_time",
            "scan_date": scan_date,
            "month": month,
        })
    save_data()


def main() -> None:
    load_data()
    seed()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print("\n  LEARN 2EARN dev server (Python)", flush=True)
    print(f"  Portal : http://localhost:{PORT}", flush=True)
    print(f"  API    : http://localhost:{PORT}/api/v1", flush=True)
    print(f"  Kiosk  : http://localhost:{PORT}/dev/kiosk.html  (live test QR)", flush=True)
    print("  Demo   : demo_student / demo12345", flush=True)
    if ALLOW_FOREIGN_QR:
        print("  Note   : ALLOW_FOREIGN_QR=1 - unverified codes from another issuer are accepted\n", flush=True)
    else:
        print("", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
