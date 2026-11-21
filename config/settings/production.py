import os
from .base import *  # noqa: F403

DEBUG = False
if not SECRET_KEY or len(SECRET_KEY) < 50:
    raise RuntimeError("DJANGO_SECRET_KEY must be configured with at least 50 characters in production.")
if not QR_SIGNING_SECRET or len(QR_SIGNING_SECRET) < 48:
    raise RuntimeError("ATTENDANCE_SECRET must be configured with at least 48 characters in production.")
for name, value in (("DJANGO_SECRET_KEY", SECRET_KEY), ("ATTENDANCE_SECRET", QR_SIGNING_SECRET)):
    if value.lower().startswith(("generate-", "change-me", "replace-", "your-")) or len(set(value)) < 12:
        raise RuntimeError(f"{name} appears to be a placeholder or low-entropy value; generate a new random secret.")
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise RuntimeError("Production requires PostgreSQL. Set DATABASE_URL to a PostgreSQL connection URL.")
if not ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must contain the production host.")
if all(host in {"localhost", "127.0.0.1", "testserver"} for host in ALLOWED_HOSTS):
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must include the deployed attendance hostname.")
REDIS_URL = os.environ.get("REDIS_URL", CELERY_BROKER_URL)
if not REDIS_URL:
    raise RuntimeError("Configure REDIS_URL for shared production cache and rate limiting.")
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
