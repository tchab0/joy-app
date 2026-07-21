from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-placeholder-change-in-prod")
DEBUG = False
ALLOWED_HOSTS = ["jazz-orchestra-yonnais.fr", "www.jazz-orchestra-yonnais.fr", "dev.jazz-orchestra-yonnais.fr", "127.0.0.1", "localhost"]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "channels",
    "users.apps.UsersConfig",
    "core",
    "orchestra",
    "events",
    "planning.apps.PlanningConfig",
    "feedback.apps.FeedbackConfig",
    "chat.apps.ChatConfig",
    "repertoire.apps.RepertoireConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.NoIndexPrivateMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "feedback.context_processors.page_feedback",
                "users.context_processors.nav_access",
                "core.context_processors.seo",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
        },
    },
}

CHAT_ATTACHMENT_MAX_BYTES = int(
    os.environ.get("CHAT_ATTACHMENT_MAX_BYTES", str(25 * 1024 * 1024))
)
CHAT_DIGEST_INTERVAL_MINUTES = int(os.environ.get("CHAT_DIGEST_INTERVAL_MINUTES", "30"))

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = Path("/srv/jazz-orchestra-yonnais/media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "users.User"

LOGIN_URL = "/compte/connexion/"
LOGIN_REDIRECT_URL = "/compte/"
LOGOUT_REDIRECT_URL = "/"

# Auth OTP (canal téléphone via backend configurable)
OTP_PEPPER = os.environ.get("OTP_PEPPER", "")
TOTP_ISSUER = os.environ.get("TOTP_ISSUER", "Jazz Orchestra Yonnais")
SMS_BACKEND = os.environ.get("SMS_BACKEND", "console")
SMS_HTTP_URL = os.environ.get("SMS_HTTP_URL", "")
SMS_HTTP_METHOD = os.environ.get("SMS_HTTP_METHOD", "POST")
SMS_HTTP_TO_FIELD = os.environ.get("SMS_HTTP_TO_FIELD", "to")
SMS_HTTP_BODY_FIELD = os.environ.get("SMS_HTTP_BODY_FIELD", "message")
SMS_HTTP_API_KEY = os.environ.get("SMS_HTTP_API_KEY", "")
SMS_HTTP_API_KEY_HEADER = os.environ.get("SMS_HTTP_API_KEY_HEADER", "Authorization")

# Web Push (VAPID) — PEM privée peut contenir \n échappés dans .env
def _env_get(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    if val:
        return val
    env_path = Path(os.environ.get("JOY_ENV_FILE", "/srv/jazz-orchestra-yonnais/.env"))
    if not env_path.is_file():
        return default
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() != name:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    except OSError:
        return default
    return default


VAPID_PUBLIC_KEY = _env_get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = _env_get("VAPID_PRIVATE_KEY", "")
VAPID_ADMIN_EMAIL = _env_get(
    "VAPID_ADMIN_EMAIL",
    os.environ.get("ADMIN_EMAIL", "admin@jazz-orchestra-yonnais.fr"),
)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.hostinger.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "admin@jazz-orchestra-yonnais.fr")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "JOY <admin@jazz-orchestra-yonnais.fr>")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@jazz-orchestra-yonnais.fr")
SITE_URL = os.environ.get("SITE_URL", "https://jazz-orchestra-yonnais.fr")
GOOGLE_SITE_VERIFICATION = os.environ.get("GOOGLE_SITE_VERIFICATION", "")
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "joy-app-default-cache",
        "TIMEOUT": 300,
    }
}

CACHE_TTL_HOME = 300
CACHE_TTL_CONCERTS = 300
CACHE_TTL_GOODIES = 1800
CACHE_TTL_DON = 1800
CACHE_TTL_ADHESION = 1800

