from .base import *

DEBUG = True

ALLOWED_HOSTS = [
    "dev.jazz-orchestra-yonnais.fr",
    "127.0.0.1",
    "localhost",
]

CSRF_TRUSTED_ORIGINS = [
    "https://dev.jazz-orchestra-yonnais.fr",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
