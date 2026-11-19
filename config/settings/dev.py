from .base import *  # noqa: F403
import secrets
SECRET_KEY = SECRET_KEY or secrets.token_urlsafe(64)
QR_SIGNING_SECRET = QR_SIGNING_SECRET or secrets.token_urlsafe(64)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = list(set(ALLOWED_HOSTS + ["testserver"]))  # noqa: F405
MIDDLEWARE = [item for item in MIDDLEWARE if item != "whitenoise.middleware.WhiteNoiseMiddleware"]  # noqa: F405
