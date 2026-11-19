# Serving the student portal from Django at `/student/`

Engineer B owns the Django project. This document is the handoff: the exact files, routing
and static settings needed to serve this portal at `https://<host>/student/`, with the mentor
portal left untouched at `/`. Nothing here modifies Engineer B's project; every snippet is an
instruction for that team to apply.

The portal itself is plain HTML, CSS and JavaScript with no build step. All of its asset
references are relative (`styles.css`, `app.js`, `vendor/...`, `assets/...`), so it works when
served from any path, including `/student/`.

---

## 1. Files this repository contributes

| File / folder | Purpose | Where it goes in Django |
|---|---|---|
| `index.html` | Portal markup (single page) | `templates/student/index.html`, with the static tags from §3 |
| `styles.css` | All styling, responsive breakpoints | `static/student/styles.css` |
| `app.js` | Auth, scan, history, all API calls | `static/student/app.js` |
| `vendor/html5-qrcode.min.js` | Camera scanner, vendored (no CDN needed) | `static/student/vendor/html5-qrcode.min.js` |
| `vendor/qrcode.min.js` | Dev kiosk only, not used by the portal | `static/student/vendor/qrcode.min.js` (optional) |
| `assets/learn2earn-logo.svg` | Sidebar and sign-in logo | `static/student/assets/learn2earn-logo.svg` |
| `assets/learn2earn-mark.png` | Square mark | `static/student/assets/learn2earn-mark.png` |
| `favicon.png` | Browser icon | `static/student/favicon.png` |
| `server.py`, `dev/kiosk.html` | **Local mock only, never deploy** | not deployed |

`dev/kiosk.html` exists so the portal can be demonstrated offline. Engineer B's mentor kiosk
issues the real QR codes and is the only QR issuer in production.

---

## 2. URLs

Add one route, next to the existing mentor routes. Do not change the mentor routes.

```python
# student_portal/urls.py  (or wherever the project URLconf lives)
from django.urls import path
from django.views.generic import TemplateView

urlpatterns = [
    # ... existing mentor portal and API routes stay exactly as they are ...

    # Student portal, served at /student/ with no trailing template conflicts.
    path("student/", TemplateView.as_view(template_name="student/index.html"), name="student-portal"),
]
```

The page needs no context and no authentication at the Django level: the portal signs the
student in against `POST /api/v1/auth/student/login/` and holds the token in `sessionStorage`.

Because `app.js` derives the API base from the page's own origin, serving the page at
`/student/` on the same host makes it call `/api/v1/...` automatically. No configuration is
needed for production. For a split deployment, set the override in §5.

---

## 3. Template with `{% static %}`

Copy `index.html` to `templates/student/index.html`, then make five edits. The result:

```django
{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#052c6b">
  <title>LEARN 2EARN · Student Attendance Portal</title>
  <link rel="icon" href="{% static 'student/favicon.png' %}" type="image/png">
  <link rel="stylesheet" href="{% static 'student/styles.css' %}">
  <script src="{% static 'student/vendor/html5-qrcode.min.js' %}"></script>
  <script defer src="{% static 'student/app.js' %}"></script>
</head>
<body>
  ...
        <img class="brand-logo" src="{% static 'student/assets/learn2earn-logo.svg' %}" alt="Learn2Earn">
  ...
        <div class="auth-brand"><img class="brand-logo" src="{% static 'student/assets/learn2earn-logo.svg' %}" alt="Learn2Earn"></div>
  ...
</body>
</html>
```

That is the complete list of asset references: `favicon.png`, `styles.css`,
`vendor/html5-qrcode.min.js`, `app.js`, and `assets/learn2earn-logo.svg` twice. Delete the
`document.write` CDN fallback block that follows the scanner `<script>` tag; the library is
vendored, so the fallback only adds a network dependency.

One-line conversion, if it is easier than hand-editing:

```bash
sed -i \
  -e "s|href=\"favicon.png\"|href=\"{% static 'student/favicon.png' %}\"|" \
  -e "s|href=\"styles.css\"|href=\"{% static 'student/styles.css' %}\"|" \
  -e "s|src=\"vendor/html5-qrcode.min.js\"|src=\"{% static 'student/vendor/html5-qrcode.min.js' %}\"|" \
  -e "s|src=\"app.js\"|src=\"{% static 'student/app.js' %}\"|" \
  -e "s|src=\"assets/learn2earn-logo.svg\"|src=\"{% static 'student/assets/learn2earn-logo.svg' %}\"|g" \
  templates/student/index.html
sed -i '1i {% load static %}' templates/student/index.html
```

With `STATIC_URL = "/static/"`, the browser requests `/static/student/styles.css`, which
resolves correctly no matter which path the page itself is served from. Using `{% static %}`
is preferred over relative paths because it keeps working if the portal later moves to a CDN
or a versioned static prefix.

---

## 4. Settings

```python
# settings.py
STATIC_URL = "/static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",          # holds static/student/... from this repository
]

# collectstatic target for production (WhiteNoise, S3, nginx, whatever you already use)
STATIC_ROOT = BASE_DIR / "staticfiles"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        # ... existing options unchanged ...
    },
]
```

If the project already has `STATIC_URL`, `STATICFILES_DIRS` and `TEMPLATES["DIRS"]`, only add
the `student/` folder to them. Do not change `STATIC_URL` for this integration.

---

## 5. Optional: split API host

If the portal and the API end up on different hosts, set the base URL in one place. Either the
meta tag in `templates/student/index.html`:

```django
<meta name="learn2earn-api-base" content="https://api.example.com/api/v1">
```

or a global before `app.js` loads:

```django
<script>window.LEARN2EARN_API_BASE = "https://api.example.com/api/v1";</script>
```

When set, the backend must allow the portal's origin in CORS and accept the `Authorization`
header. Both defaults (same origin, and the production host for `file://`) need no edit.

---

## 6. Alternative for local development only

If a developer wants to look at the portal without touching templates, serve the folder
straight from Django's development static view. This is **not** for production: it bypasses
`collectstatic` and caching.

```python
from django.urls import re_path
from django.views.static import serve

urlpatterns += [
    re_path(r"^student/(?P<path>.*)$", serve, {"document_root": BASE_DIR / "student-portal"}),
]
```

Here the whole repository folder sits at `student-portal/` and the page is reached at
`/student/index.html`. Relative asset paths resolve under `/student/`, so no template edits are
needed. For anything beyond local use, follow §2 to §4.

---

## 7. Post-deploy checklist for Engineer B

1. `https://<host>/student/` returns the portal, not the mentor portal and not a 404.
2. Browser devtools show `styles.css`, `app.js`, `vendor/html5-qrcode.min.js` and the logo all
   loading `200` from `/static/student/...`.
3. Sign-in reaches `POST /api/v1/auth/student/login/` and returns `{token, student}`.
4. `Authorization: Token <token>` (never `Bearer`) is sent on `/student/attendance-history/`
   and `/attendance/scan/`.
5. `GET /api/v1/student/attendance-history/` returns a bare JSON list.
6. Camera scanning works over HTTPS on a phone (a plain-HTTP LAN address will block
   `getUserMedia`).
7. The mentor portal at `/` is unchanged.
