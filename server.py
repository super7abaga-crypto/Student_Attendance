#!/usr/bin/env python3
"""
Engineer A — LOCAL DEVELOPMENT MOCK of Engineer B's Django API (NOT for production)
----------------------------------------------------------------------------------
This file exists only so the student portal can be run and demonstrated offline.
It mirrors the endpoints and error codes in API_CONTRACT.md. It is NOT the
integration target: production traffic goes to Engineer B's Django backend at
https://fellowship.learn2earn.ng/api/v1/ .

    python server.py                 -> http://127.0.0.1:8000/student/

It also serves the portal, including under /student/, so the Django hosting paths
can be exercised locally.

Mocked behaviour (the real decisions belong to Engineer B):
  - POST /api/v1/auth/student/login/         token + student profile (12h token)
  - POST /api/v1/auth/logout/                clears nothing server-side (stateless)
  - GET  /api/v1/student/attendance-history/ bare list of records
  - POST /api/v1/attendance/scan/            201 / 409 / 403 with contract codes
  - GET  /api/v1/dev/qr                      mentor-kiosk QR JSON for scan testing
  - POST /api/v1/dev/reset                   wipe local data

Session cutoffs (WAT) and the "exactly at the cutoff is late" rule follow the
current contract: morning 09:10, afternoon 13:10, evening 17:10.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import mimetypes
import os
import pathlib
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DATA_FILE = pathlib.Path(os.environ.get("DATA_FILE") or (ROOT / "dev" / ".data.json"))

PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")

APP_SECRET = os.environ.get("APP_SECRET") or secrets.token_hex(32)
QR_SECRET = os.environ.get("QR_SECRET") or secrets.token_hex(32)

TOKEN_TTL_MS = 12 * 60 * 60 * 1000          # 12 hours, per contract
QR_TTL_SECONDS = 30   # QR tokens expire after 30 seconds
MOCK_ATTENDANCE_ACTION = os.environ.get("MOCK_ATTENDANCE_ACTION", "check_in")  # mirrors Engineer B: check_in / check_out

WAT_OFFSET_MIN = 60                          # Africa/Lagos is UTC+1 all year
SESSIONS = {
    "morning":   {"label": "Morning Session",   "start": 9 * 60,  "cutoff": 9 * 60 + 10},
    "afternoon": {"label": "Afternoon Session", "start": 13 * 60, "cutoff": 13 * 60 + 10},
    "evening":   {"label": "Evening Session",   "start": 17 * 60, "cutoff": 17 * 60 + 10},
}
# A session accepts scans from its start until SESSION_OPEN_MINUTES after the start.
# Outside that window the session is inactive and the server refuses the scan.
SESSION_OPEN_MINUTES = int(os.environ.get("SESSION_OPEN_MINUTES", "180"))

CAMPUS = {
    "name": os.environ.get("CAMPUS_NAME", "Lagos Campus"),
    "latitude": float(os.environ.get("CAMPUS_LAT", "6.5244")),
    "longitude": float(os.environ.get("CAMPUS_LON", "3.3792")),
    "radius_m": float(os.environ.get("CAMPUS_RADIUS_M", "300")),
}
MAX_ACCURACY_M = float(os.environ.get("MAX_ACCURACY_M", "100"))

LOCK = threading.Lock()
DB = {"students": [], "attendance": []}


# ------------------------------------------------------------------ helpers ---
def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def iso_ms(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# DEV/TEST ONLY: pin the mock's WAT clock (e.g. MOCK_NOW_WAT=09:10) so cutoff behaviour
# can be tested deterministically. Never set this outside local testing.
MOCK_NOW_WAT = os.environ.get("MOCK_NOW_WAT", "").strip()


def wat_now() -> datetime:
    real = datetime.now(timezone.utc) + timedelta(minutes=WAT_OFFSET_MIN)
    if not MOCK_NOW_WAT:
        return real
    try:
        hour, minute = (int(part) for part in MOCK_NOW_WAT.split(":")[:2])
    except ValueError:
        return real
    return real.replace(hour=hour, minute=minute, second=0, microsecond=0)


def wat_parts(dt: datetime | None = None) -> dict:
    shifted = (dt or wat_now())
    return {
        "date": shifted.strftime("%Y-%m-%d"),
        "month": shifted.strftime("%Y-%m"),
        "minutes": shifted.hour * 60 + shifted.minute,
        "time": shifted.strftime("%H:%M:%S"),
        "time_short": shifted.strftime("%H:%M"),
    }


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(value: str, secret: str) -> str:
    return b64url(hmac.new(secret.encode(), value.encode(), hashlib.sha256).digest())


def hash_password(password: str, salt: str | None = None) -> dict:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
    return {"salt": salt, "hash": digest.hex()}


def verify_password(password: str, salt: str, expected: str) -> bool:
    candidate = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64).hex()
    return hmac.compare_digest(candidate, expected)


def issue_token(student_id: str) -> str:
    payload = b64url(json.dumps({"sub": student_id, "exp": now_ms() + TOKEN_TTL_MS}).encode())
    return f"{payload}.{sign(payload, APP_SECRET)}"


def read_token(token: str) -> dict | None:
    if not isinstance(token, str) or token.count(".") != 1:
        return None
    payload, signature = token.split(".")
    if not hmac.compare_digest(sign(payload, APP_SECRET), signature):
        return None
    try:
        claims = json.loads(unb64url(payload))
    except Exception:
        return None
    if not claims.get("exp") or claims["exp"] < now_ms():
        return None
    return claims


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def load_data() -> None:
    try:
        raw = json.loads(DATA_FILE.read_text())
        if isinstance(raw.get("students"), list):
            DB["students"] = raw["students"]
        if isinstance(raw.get("attendance"), list):
            DB["attendance"] = raw["attendance"]
    except Exception:
        pass


def save_data() -> None:
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(DB, indent=2))
    except Exception:
        pass


def public_student(student: dict) -> dict:
    return {
        "id": student["id"],
        "full_name": student["full_name"],
        "username": student["username"],
        "campus": student.get("campus", ""),
    }


def record_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "username": row["username"],
        "session_type": row["session_type"],
        "attendance_date": row["attendance_date"],
        "scanned_at": row["scanned_at"],
        "scan_time_wat": row["scan_time_wat"],
        "status": row["status"],
        "attendance_action": row.get("attendance_action", MOCK_ATTENDANCE_ACTION),
    }


# --------------------------------------------------------------------- seed ---
def seed() -> None:
    if DB["students"]:
        return
    password = hash_password("demo12345")
    student = {
        "id": str(uuid.uuid4()),
        "full_name": "Demo Student",
        "username": "demo_student",
        "password_salt": password["salt"],
        "password_hash": password["hash"],
        "campus": CAMPUS["name"],
        "is_active": True,
        "created_at": iso_ms(datetime.now(timezone.utc)),
    }
    DB["students"].append(student)

    today = datetime.strptime(wat_parts()["date"], "%Y-%m-%d")
    for offset, session_type, status, time_wat in (
        (1, "morning", "late", "09:14:22"),
        (2, "morning", "on_time", "09:03:10"),
        (3, "afternoon", "on_time", "13:02:47"),
    ):
        scan_date = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        if scan_date[:7] != wat_parts()["month"]:
            continue
        hour, minute, second = (int(part) for part in time_wat.split(":"))
        scanned = datetime.fromisoformat(f"{scan_date}T{hour:02d}:{minute:02d}:{second:02d}+01:00")
        DB["attendance"].append({
            "id": str(uuid.uuid4()),
            "student_id": student["id"],
            "full_name": student["full_name"],
            "username": student["username"],
            "session_type": session_type,
            "attendance_date": scan_date,
            "scanned_at": iso_ms(scanned),
            "scan_time_wat": time_wat,
            "status": status,
            "campus": CAMPUS["name"],
        })
    save_data()


# ---------------------------------------------------------------- QR helpers ---
def issue_qr(session_type: str | None = None) -> dict:
    session = session_type or active_session()
    token_body = b64url(json.dumps({
        "s": session,
        "d": wat_parts()["date"],
        "n": secrets.token_hex(6),
    }).encode())
    token = f"{token_body}.{sign(token_body, QR_SECRET)}"
    expires_at = int(datetime.now(timezone.utc).timestamp()) + QR_TTL_SECONDS
    return {
        "payload": json.dumps({"version": 1, "token": token, "expires_at": expires_at}),
        "session_type": session,
        "session_name": SESSIONS[session]["label"],
        "expires_at": expires_at,
        "cutoff_wat": f"{SESSIONS[session]['cutoff'] // 60:02d}:{SESSIONS[session]['cutoff'] % 60:02d}",
        "server_time_wat": wat_parts()["time"],
        "campus": CAMPUS["name"],
    }


def active_session() -> str:
    """The session a mentor kiosk would be showing: the one open right now,
    otherwise the next one due today."""
    minutes = wat_parts()["minutes"]
    order = ["morning", "afternoon", "evening"]
    for key in order:
        if SESSIONS[key]["start"] <= minutes < SESSIONS[key]["start"] + SESSION_OPEN_MINUTES:
            return key
    for key in order:
        if minutes < SESSIONS[key]["start"]:
            return key
    return "evening"


def parse_qr(qr_payload) -> dict:
    if not isinstance(qr_payload, str) or not qr_payload.strip():
        return {"error": ("invalid_qr", "That QR code could not be read. Scan the code again.", 400)}
    try:
        data = json.loads(qr_payload)
    except Exception:
        return {"error": ("invalid_qr", "That is not an attendance QR code.", 400)}
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("token"), str):
        return {"error": ("invalid_qr", "That is not an attendance QR code.", 400)}

    token = data["token"]
    if token.count(".") != 1:
        return {"error": ("invalid_qr", "That QR code is damaged. Ask your mentor to show a new one.", 400)}
    body, signature = token.split(".")
    if not hmac.compare_digest(sign(body, QR_SECRET), signature):
        return {"error": ("invalid_qr", "This QR code was not issued by the attendance system.", 400)}
    try:
        claims = json.loads(unb64url(body))
    except Exception:
        return {"error": ("invalid_qr", "That QR code is damaged. Ask your mentor to show a new one.", 400)}

    expires_at = data.get("expires_at")
    if not isinstance(expires_at, (int, float)) or expires_at < datetime.now(timezone.utc).timestamp():
        return {"error": ("qr_expired", "This QR code has expired. Scan the current one.", 403)}
    if claims.get("d") != wat_parts()["date"]:
        return {"error": ("qr_expired", "This QR code is for a different day.", 403)}
    session = claims.get("s")
    if session not in SESSIONS:
        return {"error": ("invalid_qr", "That QR code is for an unknown session.", 400)}
    return {"session": session}


# ------------------------------------------------------------------ handler ---
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Learn2EarnDevMock/1.0"

    def log_message(self, fmt, *args):
        pass

    # -- plumbing --
    def cors(self) -> None:
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
            data = json.loads(raw)
        except Exception:
            raise ValueError("Invalid JSON body")
        return data if isinstance(data, dict) else {}

    def auth_token(self) -> str | None:
        header = self.headers.get("Authorization") or ""
        if header.startswith("Token "):
            return header[6:].strip()
        return None

    def authed_student(self) -> dict | None:
        token = self.auth_token()
        if not token:
            return None
        claims = read_token(token)
        if not claims:
            return None
        return next((s for s in DB["students"] if s["id"] == claims["sub"]), None)

    # -- verbs --
    def do_OPTIONS(self):
        self.drain_body()
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.drain_body()
        self.dispatch("GET")

    def do_POST(self):
        self.drain_body()
        self.dispatch("POST")

    def dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        route = url.path

        try:
            if route.startswith("/api/v1/"):
                return self.api(route[len("/api/v1"):], method, parse_qs(url.query))
            if method != "GET":
                return self.send_json(404, {"detail": f"No route for {method} {route}"})
            return self.serve_static(route)
        except ValueError as exc:
            return self.send_json(400, {"detail": str(exc)})
        except Exception as exc:  # pragma: no cover - defensive
            return self.send_json(500, {"detail": f"Dev server error: {exc}"})

    # -- API --
    def api(self, route: str, method: str, query: dict) -> None:
        if route == "/auth/student/login/" and method == "POST":
            body = self.read_json()
            username = str(body.get("username") or "").strip().lower().replace(" ", "")
            password = str(body.get("password") or "")
            with LOCK:
                student = next((s for s in DB["students"] if s["username"] == username), None)
                if not student or not verify_password(password, student["password_salt"], student["password_hash"]):
                    return self.send_json(401, {"detail": "Incorrect username or password."})
                if not student.get("is_active", True):
                    return self.send_json(403, {"detail": "Your account is not active. Contact your mentor."})
                return self.send_json(200, {"token": issue_token(student["id"]), "student": public_student(student)})

        if route == "/auth/logout/" and method == "POST":
            if not self.authed_student():
                return self.send_json(401, {"detail": "Authentication credentials were not provided."})
            return self.send_json(200, {"detail": "Logged out."})

        if route == "/student/attendance-history/" and method == "GET":
            student = self.authed_student()
            if not student:
                return self.send_json(401, {"detail": "Authentication credentials were not provided."})
            rows = [record_view(r) for r in DB["attendance"] if r["student_id"] == student["id"]]
            rows.sort(key=lambda r: (r["attendance_date"], r["scan_time_wat"]), reverse=True)
            return self.send_json(200, rows)   # bare list, per contract

        if route == "/attendance/scan/" and method == "POST":
            return self.scan()

        if route == "/dev/qr" and method == "GET":
            requested = (query.get("session") or [None])[0]
            session = requested if requested in SESSIONS else None
            return self.send_json(200, issue_qr(session))

        if route == "/dev/reset" and method == "POST":
            with LOCK:
                DB["students"].clear()
                DB["attendance"].clear()
                seed()
                return self.send_json(200, {"ok": True, "students": len(DB["students"])})

        return self.send_json(404, {"detail": f"No route for {method} /api/v1{route}"})

    def scan(self) -> None:
        student = self.authed_student()
        if not student:
            return self.send_json(401, {"detail": "Authentication credentials were not provided."})

        body = self.read_json()
        parsed = parse_qr(body.get("qr_payload"))
        if "error" in parsed:
            code, detail, status = parsed["error"]
            return self.send_json(status, {"detail": detail, "code": code})

        latitude, longitude, accuracy = body.get("latitude"), body.get("longitude"), body.get("accuracy")
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            return self.send_json(400, {"detail": "Location is required to record attendance.", "code": "gps_required"})
        if isinstance(accuracy, (int, float)) and accuracy > MAX_ACCURACY_M:
            return self.send_json(403, {
                "detail": f"Your location accuracy is too low to verify attendance (±{round(accuracy)} m). Move to an open area and try again.",
                "code": "gps_accuracy",
            })
        distance = distance_m(float(latitude), float(longitude), CAMPUS["latitude"], CAMPUS["longitude"])
        if distance > CAMPUS["radius_m"]:
            return self.send_json(403, {
                "detail": "You are outside the campus geofence. Move onto campus and scan again.",
                "code": "wrong_campus",
            })

        session_type = parsed["session"]
        parts = wat_parts()
        session_conf = SESSIONS[session_type]
        if not (session_conf["start"] <= parts["minutes"] < session_conf["start"] + SESSION_OPEN_MINUTES):
            return self.send_json(403, {
                "detail": "There is no active attendance session for this QR code right now.",
                "code": "session_inactive",
            })
        session_id = f"{parts['date']}-{session_type}"
        with LOCK:
            existing = next((r for r in DB["attendance"]
                             if r["student_id"] == student["id"] and r["session_type"] == session_type
                             and r["attendance_date"] == parts["date"]), None)
            if existing:
                return self.send_json(409, {
                    "detail": "Already checked in for this session.",
                    "code": "duplicate_attendance",
                    "attendance": record_view(existing),
                })

            # Exactly at the cutoff counts as late, per the current contract.
            status = "late" if parts["minutes"] >= SESSIONS[session_type]["cutoff"] else "on_time"
            row = {
                "id": str(uuid.uuid4()),
                "student_id": student["id"],
                "full_name": student["full_name"],
                "username": student["username"],
                "session_type": session_type,
                "attendance_date": parts["date"],
                "scanned_at": iso_ms(datetime.now(timezone.utc)),
                "scan_time_wat": parts["time"],
                "status": status,
                # MOCK ONLY placeholder. Engineer B's contract owns this enum; the
                # frontend renders whatever arrives and never branches on it.
                "attendance_action": MOCK_ATTENDANCE_ACTION,
                "campus": student.get("campus", CAMPUS["name"]),
                "session_id": session_id,
                "accuracy": accuracy,
                "latitude": latitude,
                "longitude": longitude,
                "distance_m": round(distance, 1),
            }
            DB["attendance"].append(row)
            save_data()
            return self.send_json(201, {"detail": "Attendance recorded.", "attendance": record_view(row)})

    # -- static --
    def serve_static(self, route: str) -> None:
        if route in ("/", "/student", "/student/"):
            route = "/index.html"
        elif route.startswith("/student/"):
            route = route[len("/student"):]
        if route == "/dev/qr" or route.startswith("/api/"):
            return self.send_json(404, {"detail": "Not found"})

        target = (ROOT / route.lstrip("/")).resolve()
        if not str(target).startswith(str(ROOT)) or not target.is_file():
            return self.send_json(404, {"detail": f"Not found: {route}"})

        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    load_data()
    seed()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("\n  Learn2Earn — LOCAL MOCK of Engineer B's Django API (dev only)", flush=True)
    print(f"  Student portal : http://{HOST}:{PORT}/student/", flush=True)
    print(f"  API base       : http://{HOST}:{PORT}/api/v1", flush=True)
    print(f"  Mentor kiosk   : http://{HOST}:{PORT}/dev/kiosk.html  (live test QR)", flush=True)
    print(f"  Demo student   : demo_student / demo12345  ({CAMPUS['name']})", flush=True)
    print(f"  Geofence       : {CAMPUS['latitude']}, {CAMPUS['longitude']}  ±{CAMPUS['radius_m']:.0f} m, "
          f"max accuracy {MAX_ACCURACY_M:.0f} m", flush=True)
    print("  Production API : https://fellowship.learn2earn.ng/api/v1/  (Engineer B)\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
