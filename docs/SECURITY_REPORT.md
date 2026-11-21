# Security changes and verification boundary

- Replaced the active Node JSON file server with Django; the root Node entrypoint now exits with a migration notice. The Django frontend serves only an explicit whitelist of app assets. JSON storage, archived reports, legacy code and `.env` are not served.
- Production refuses absent/short/example secrets, localhost-only host lists and non-PostgreSQL databases. Local development creates ephemeral secrets and uses a private SQLite file.
- Mentor sessions are individual Django sessions with CSRF checks on unsafe requests. Student authentication uses Django password hashes and independent DRF tokens. Rate limits cover authentication and scans.
- Campus membership and roles scope querysets and mutations. Attendance officers have read-only permissions; export flags are checked.
- HMAC signed QR tokens include campus/session/action/run and a nonce, are exact-expiry checked, persisted for revocation, and invalidated at session close.
- Scan identity is the authenticated student relation. Server-side Haversine distance and accuracy enforce the assigned campus; no user-submitted username establishes identity.
- Database uniqueness plus nested atomic writes protects duplicate records. Corrections append an adjustment and audit record. Monthly closure retains original logs and is idempotent.
- CSV values are formula escaped. Exports require campus permission. Audit events are read-only in Django Admin.

The local suite is not a production security certification. PostgreSQL concurrency, TLS termination, Redis failure behavior, campus coordinates, location spoofing and real deployment secrets must be verified in the target environment. Browser GPS is not cryptographic proof of location.
