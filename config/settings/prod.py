from .base import *
import os

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
# Never enable DEBUG in production (even if DJANGO_DEBUG is set by mistake).
DEBUG = False

ALLOWED_HOSTS = ["jazz-orchestra-yonnais.fr", "www.jazz-orchestra-yonnais.fr"]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CSRF_TRUSTED_ORIGINS",
        "https://jazz-orchestra-yonnais.fr,https://www.jazz-orchestra-yonnais.fr"
    ).split(",")
    if origin.strip()
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DATABASE_NAME"],
        "USER": os.environ["DATABASE_USER"],
        "PASSWORD": os.environ["DATABASE_PASSWORD"],
        "HOST": os.environ.get("DATABASE_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DATABASE_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

CSRF_COOKIE_HTTPONLY = False
SECURE_REFERRER_POLICY = "same-origin"

SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False

# Shared cache across gunicorn/daphne workers (Channels stays on REDIS_URL /0).
_redis_cache_url = os.environ.get("REDIS_CACHE_URL") or os.environ.get(
    "REDIS_URL", "redis://127.0.0.1:6379/0"
)
if _redis_cache_url.rstrip("/").endswith("/0"):
    _redis_cache_url = _redis_cache_url.rstrip("/")[:-1] + "1"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": _redis_cache_url,
        "TIMEOUT": 300,
    }
}
