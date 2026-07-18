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
INSTALLED_APPS += [
    "debug_toolbar",
]

MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    *MIDDLEWARE,
]

INTERNAL_IPS = [
    "127.0.0.1",
]

INSTALLED_APPS += [
    "compressor",
]

STATICFILES_FINDERS = list(globals().get("STATICFILES_FINDERS", [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
])) + [
    "compressor.finders.CompressorFinder",
]

COMPRESS_ENABLED = True
COMPRESS_OFFLINE = False
