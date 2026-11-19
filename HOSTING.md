# Hosting the student portal at `/student/` — Django handoff

This document is for **Engineer B**. Nothing here changes the Django project; it only
describes what the student portal needs in order to be served correctly at `/student/`,
alongside the mentor portal at `/`.

## What the portal is

A static bundle: one HTML page, one CSS file, one JS file, a vendored scanner library, a
logo set and a favicon. No build step, no npm, no server-side rendering.

```
index.html
styles.css
app.js
favicon.png
assets/learn2earn-logo.svg
assets/learn2earn-mark.png
vendor/html5-qrcode.min.js
```

`server.py`, `dev/` and `docs/` are development-only and should not be deployed.

## Why the paths already work

Every asset reference in `index.html` is **relative** (`styles.css`, `app.js`,
`vendor/…`, `assets/…`, `favicon.png`). There is no leading `/`, so the same files resolve
correctly at `/`, `/student/` and any other prefix. Keep them relative; do not rewrite them
to absolute paths.

The API base URL is resolved at runtime to `<page origin>/api/v1`, so a page served from
`https://<host>/student/` calls `https://<host>/api/v1/` with no configuration. To point a
deployment somewhere else, set the `learn2earn-api-base` meta tag in `index.html` or define
`window.LEARN2EARN_API_BASE` before `app.js` loads.

## Option A — Django template + static files (recommended)

1. Copy `index.html` to `templates/student/index.html`.
2. Copy the rest of the bundle into your static directory, for example:

   ```
   static/student/styles.css
   static/student/app.js
   static/student/favicon.png
   static/student/assets/learn2earn-logo.svg
   static/student/assets/learn2earn-mark.png
   static/student/vendor/html5-qrcode.min.js
   ```

3. Because the template now lives one level deeper than the static root, point the relative
   references at the static prefix, keeping them relative to `/student/`:

   ```html
   <link rel="stylesheet" href="static/student/styles.css">
   <script src="static/student/vendor/html5-qrcode.min.js"></script>
   <script defer src="static/student/app.js"></script>
   <link rel="icon" href="static/student/favicon.png">
   <img src="static/student/assets/learn2earn-logo.svg" alt="Learn2Earn">
   ```

   If you prefer `{% static %}`, use `{% static 'student/styles.css' %}` etc. Either way the
   URLs must resolve under `/student/`.

4. Route it:

   ```python
   # urls.py
   from django.views.generic import TemplateView

   urlpatterns += [
       path("student/", TemplateView.as_view(template_name="student/index.html"), name="student-portal"),
   ]
   ```

5. Make sure `STATIC_URL` is reachable in production (`collectstatic` + your web server or
   WhiteNoise). The portal requests no other files.

## Option B — serve the bundle as static files only

Keep the bundle intact in `static/student/` (including `index.html`) and let the web server
return it:

```nginx
location = /student { return 301 /student/; }
location /student/ {
    alias /srv/app/static/student/;
    try_files $uri $uri/ /student/index.html;
}
```

With this option the relative references in `index.html` work unchanged.

## Requirements checklist

- [ ] `GET /student/` returns the portal HTML with `Content-Type: text/html`.
- [ ] `styles.css`, `app.js`, `favicon.png`, `assets/*`, `vendor/html5-qrcode.min.js` all return `200`.
- [ ] `GET /api/v1/student/attendance-history/` works from the portal origin (same origin needs no CORS).
- [ ] `POST /api/v1/auth/student/login/` and `POST /api/v1/attendance/scan/` are reachable.
- [ ] HTTPS in production: camera and geolocation are blocked on plain HTTP except on `localhost`.
- [ ] The mentor portal stays at `/` and the student portal at `/student/`; they share the API only.
- [ ] `404`/`500` handling does not swallow `/student/` (avoid a catch-all SPA route in front of it).

## Local check before deploying

```bash
python server.py
# portal:  http://127.0.0.1:8000/student/
# api:     http://127.0.0.1:8000/api/v1/
```

The local mock serves the bundle under `/student/` with exactly the same relative paths, so
a page that works there will work under Django with the mapping above.
