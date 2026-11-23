#!/usr/bin/env python3
"""
API test suite for the student portal contract (standard library only).

It boots the local mock (server.py) on a free port with fixed dev secrets and a
throwaway data file, then exercises every endpoint and error code in
API_CONTRACT.md. It never touches Engineer B's backend and never touches
dev/.data.json.

    python3 tests/api-test.py            # from the repository root
    python3 tests/api-test.py -v         # show each request/response

Exit code 0 = all checks passed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv
APP_SECRET = "test-app-secret"
QR_SECRET = "test-qr-secret"
CAMPUS = {"lat": 6.5244, "lon": 3.3792}

passed = failed = 0
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        failures.append(name)
        print(f"  FAIL  {name}" + (f"  ->  {detail}" if detail else ""))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def sign(value: str, secret: str) -> str:
    return b64url(hmac.new(secret.encode(), value.encode(), hashlib.sha256).digest())


def make_token(exp_ms: int) -> str:
    body = b64url(json.dumps({"sub": "test-student", "exp": exp_ms}).encode())
    return f"{body}.{sign(body, APP_SECRET)}"


def make_qr(session: str, expires_at: int, scan_date: str) -> str:
    body = b64url(json.dumps({"s": session, "d": scan_date, "n": "test"}).encode())
    token = f"{body}.{sign(body, QR_SECRET)}"
    return json.dumps({"version": 1, "token": token, "expires_at": expires_at})


class Client:
    def __init__(self, base: str):
        self.base = base

    def call(self, method: str, path: str, body=None, token: str | None = None,
             scheme: str = "Token"):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"{scheme} {token}")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read() or b"null")
                status = response.status
        except urllib.error.HTTPError as error:
            payload = json.loads(error.read() or b"null")
            status = error.code
        if VERBOSE:
            print(f"    {method} {path} -> {status} {json.dumps(payload)[:140]}")
        return status, payload


class Mock:
    """Boot server.py on a free port with a throwaway data file."""

    def __init__(self, now_wat: str | None = None, data_file: Path | None = None):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}/api/v1"
        self.root_url = f"http://127.0.0.1:{self.port}"
        self.data_file = data_file or Path(tempfile.mkdtemp()) / "data.json"
        env = {
            **os.environ,
            "PORT": str(self.port),
            "APP_SECRET": APP_SECRET,
            "QR_SECRET": QR_SECRET,
            "DATA_FILE": str(self.data_file),
            "CAMPUS_LAT": str(CAMPUS["lat"]),
            "CAMPUS_LON": str(CAMPUS["lon"]),
        }
        env.pop("MOCK_NOW_WAT", None)
        if now_wat:
            env["MOCK_NOW_WAT"] = now_wat
        self.proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.client = Client(self.base)
        for _ in range(80):
            try:
                self.client.call("GET", "/dev/qr")
                return
            except Exception:
                time.sleep(0.15)
        raise RuntimeError("mock server did not start")

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def login(client: Client) -> str:
    status, body = client.call("POST", "/auth/student/login/",
                               {"username": "demo_student", "password": "demo12345"})
    check("valid login returns 200", status == 200, status)
    check("login returns a token", bool(body.get("token")), str(body)[:80])
    check("login returns student profile",
          {"full_name", "username", "campus"} <= set(body.get("student", {})),
          str(body.get("student"))[:120])
    return body.get("token", "")


def scan_body(client: Client, session: str | None = None) -> dict:
    status, qr = client.call("GET", "/dev/qr" + (f"?session={session}" if session else ""))
    return {
        "qr_payload": qr.get("payload", ""),
        "latitude": CAMPUS["lat"],
        "longitude": CAMPUS["lon"],
        "accuracy": 15,
    }


def scenario_cutoffs() -> None:
    """Exact-cutoff and after-cutoff status, using the pinned mock clock."""
    for label, now_wat, expected in [
        ("before cutoff (09:05)", "09:05", "present"),
        ("exactly at cutoff (09:10)", "09:10", "late"),
        ("after cutoff (09:11)", "09:11", "late"),
    ]:
        mock = Mock(now_wat=now_wat)
        try:
            token = login(mock.client)
            status, body = mock.client.call("POST", "/attendance/scan/",
                                            scan_body(mock.client, "morning"), token=token)
            attendance = body.get("attendance", {})
            check(f"morning scan {label} is '{expected}'",
                  status == 201 and attendance.get("status") == expected,
                  f"{status} {attendance.get('status')}")
        finally:
            mock.stop()


def scenario_three_checkpoints() -> None:
    """One student completes morning, afternoon and evening on the same local day."""
    data_file = Path(tempfile.mkdtemp()) / "day.json"
    results = {}
    for checkpoint, clock in [("morning", "09:05"), ("afternoon", "13:05"), ("evening", "17:05")]:
        mock = Mock(now_wat=clock, data_file=data_file)
        try:
            token = login(mock.client)
            status, body = mock.client.call("POST", "/attendance/scan/",
                                            scan_body(mock.client, checkpoint), token=token)
            attendance = body.get("attendance", {})
            results[checkpoint] = (status, attendance)

            # a repeat scan inside the same checkpoint is a duplicate
            again, duplicate = mock.client.call("POST", "/attendance/scan/",
                                                scan_body(mock.client, checkpoint), token=token)
            check(f"{checkpoint}: repeat scan in the same checkpoint is 409",
                  again == 409 and duplicate.get("code") == "duplicate_attendance",
                  f"{again} {duplicate.get('code')}")
            check(f"{checkpoint}: duplicate returns the existing record",
                  bool(duplicate.get("attendance")), str(duplicate)[:80])

            status_list, history = mock.client.call("GET", "/student/attendance-history/", token=token)
            today = (results[checkpoint][1] or {}).get("attendance_date")
            todays = [row for row in (history if isinstance(history, list) else [])
                      if row.get("attendance_date") == today]
            check(f"{checkpoint}: history holds one row per completed checkpoint",
                  status_list == 200 and len(todays) == len(results),
                  f"{status_list} rows={len(todays)}")
        finally:
            mock.stop()

    check("morning record is 201", results["morning"][0] == 201, results["morning"][0])
    check("afternoon record is 201", results["afternoon"][0] == 201, results["afternoon"][0])
    check("evening record is 201", results["evening"][0] == 201, results["evening"][0])
    check("morning uses check_in", results["morning"][1].get("attendance_action") == "check_in",
          results["morning"][1].get("attendance_action"))
    check("afternoon uses check_in", results["afternoon"][1].get("attendance_action") == "check_in",
          results["afternoon"][1].get("attendance_action"))
    check("evening uses check_out", results["evening"][1].get("attendance_action") == "check_out",
          results["evening"][1].get("attendance_action"))
    check("evening checkout is never late", results["evening"][1].get("status") == "present",
          results["evening"][1].get("status"))
    check("three separate records exist for one day",
          len({(r[1].get("attendance_date"), r[1].get("session_type")) for r in results.values()}) == 3,
          str([(r[1].get("attendance_date"), r[1].get("session_type")) for r in results.values()]))


def main() -> int:
    mock = Mock(now_wat="09:05")
    try:
        client = mock.client

        print("\n1. Student authentication")
        token = login(client)

        status, body = client.call("POST", "/auth/student/login/",
                                   {"username": "demo_student", "password": "wrong"})
        check("invalid login returns 401", status == 401, status)
        check("invalid login has a safe message", "detail" in body, str(body)[:80])

        status, _ = client.call("GET", "/student/attendance-history/")
        check("history without a token returns 401", status == 401, status)

        status, _ = client.call("GET", "/student/attendance-history/", token=token, scheme="Bearer")
        check("Bearer scheme is rejected (Token only)", status == 401, status)

        status, _ = client.call("GET", "/student/attendance-history/", token=make_token(1000))
        check("expired token returns 401", status == 401, status)

        status, history = client.call("GET", "/student/attendance-history/", token=token)
        check("history returns 200", status == 200, status)
        check("history is a bare JSON list", isinstance(history, list), type(history).__name__)
        if history:
            required = {"full_name", "username", "session_type", "attendance_date",
                        "scanned_at", "scan_time_wat", "status"}
            check("history rows carry the contract fields", required <= set(history[0]),
                  str(sorted(set(history[0])))[:160])
            check("history status values are backend vocabulary",
                  all(row["status"] in {"present", "late", "absent"} for row in history),
                  str([row["status"] for row in history])[:80])

        print("\n2. QR + GPS scan")
        status, qr = client.call("GET", "/dev/qr")
        check("dev kiosk issues a QR", status == 200 and qr.get("payload"), status)
        check("dev QR field is 'payload' (matches kiosk)", "payload" in qr, str(list(qr))[:120])
        check("dev QR reports WAT server time", ":" in str(qr.get("server_time_wat")),
              qr.get("server_time_wat"))

        body_in = scan_body(client, "morning")
        status, scan = client.call("POST", "/attendance/scan/", body_in, token=token)
        check("valid scan returns 201", status == 201, f"{status} {str(scan)[:120]}")
        attendance = scan.get("attendance", {})
        check("scan response nests 'attendance'", isinstance(attendance, dict), str(scan)[:100])
        required = {"full_name", "username", "session_type", "attendance_date",
                    "scanned_at", "scan_time_wat", "status", "attendance_action"}
        check("attendance carries every documented field", required <= set(attendance),
              str(sorted(set(attendance)))[:200])

        status, duplicate = client.call("POST", "/attendance/scan/", body_in, token=token)
        check("duplicate scan returns 409", status == 409, status)
        check("duplicate uses code duplicate_attendance",
              duplicate.get("code") == "duplicate_attendance", str(duplicate)[:120])
        check("duplicate preserves the original record",
              duplicate.get("attendance", {}).get("scanned_at") == attendance.get("scanned_at"),
              str(duplicate.get("attendance"))[:120])

        expired = make_qr("morning", int(time.time()) - 5, attendance.get("attendance_date", ""))
        status, body = client.call("POST", "/attendance/scan/",
                                   {**body_in, "qr_payload": expired}, token=token)
        check("expired QR returns 403 qr_expired",
              status == 403 and body.get("code") == "qr_expired", f"{status} {body.get('code')}")

        status, body = client.call("POST", "/attendance/scan/",
                                   {**body_in, "qr_payload": "not-a-qr"}, token=token)
        check("malformed QR returns 400 invalid_qr",
              status == 400 and body.get("code") == "invalid_qr", f"{status} {body.get('code')}")

        status, body = client.call("POST", "/attendance/scan/",
                                   {**body_in, "latitude": 9.0579, "longitude": 7.4951}, token=token)
        check("outside-campus GPS returns 403 wrong_campus",
              status == 403 and body.get("code") == "wrong_campus", f"{status} {body.get('code')}")

        status, body = client.call("POST", "/attendance/scan/",
                                   {**body_in, "accuracy": 420}, token=token)
        check("poor GPS accuracy returns 403 gps_accuracy",
              status == 403 and body.get("code") == "gps_accuracy", f"{status} {body.get('code')}")

        status, body = client.call("POST", "/attendance/scan/",
                                   {"qr_payload": body_in["qr_payload"]}, token=token)
        check("missing GPS returns 400 gps_required",
              status == 400 and body.get("code") == "gps_required", f"{status} {body.get('code')}")

        status, body = client.call("POST", "/attendance/scan/",
                                   scan_body(client, "evening"), token=token)
        check("scan for a session that has not opened returns 403 session_inactive",
              status == 403 and body.get("code") == "session_inactive",
              f"{status} {body.get('code')}")

        print("\n3. Session lifecycle")
        status, _ = client.call("POST", "/auth/logout/", {}, token=token)
        check("logout returns 200", status == 200, status)
        check("logout is idempotent",
              client.call("POST", "/auth/logout/", {}, token=token)[0] == 200)

        print("\n4. Static hosting under /student/")
        for asset in ["/student/", "/student/styles.css", "/student/app.js",
                      "/student/vendor/html5-qrcode.min.js", "/student/vendor/qrcode.min.js",
                      "/student/favicon.png", "/student/assets/learn2earn-logo.svg"]:
            with urllib.request.urlopen(mock.root_url + asset, timeout=10) as response:
                check(f"serves {asset}", response.status == 200, response.status)
    finally:
        mock.stop()

    print("\n5. Cutoff status from a pinned clock (mock only)")
    scenario_cutoffs()

    print("\n6. Three checkpoints in one campus-local day")
    scenario_three_checkpoints()

    print(f"\nRESULT: {passed} passed, {failed} failed")
    if failures:
        print("Failed checks: " + ", ".join(failures))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
