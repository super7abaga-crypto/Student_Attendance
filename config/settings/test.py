from .base import *  # noqa: F403
DEBUG = False
SECRET_KEY = "test-only-secret-key-that-is-not-used-outside-the-test-suite"
QR_SIGNING_SECRET = "test-only-qr-secret-that-is-not-used-outside-the-test-suite"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MIDDLEWARE = [item for item in MIDDLEWARE if item != "whitenoise.middleware.WhiteNoiseMiddleware"]
CELERY_TASK_ALWAYS_EAGER = True
