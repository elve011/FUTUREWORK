"""Minimal settings for the standalone FUTUREWORK Dev 4 mini-project."""

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [host for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if host]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "fr-fr"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "command_center.apps.CommandCenterConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("FW_DATABASE_PATH", str(BASE_DIR / "dev4.sqlite3")),
        "OPTIONS": {"timeout": float(os.environ.get("FW_SQLITE_TIMEOUT_SECONDS", "5"))},
    }
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
_default_csrf_origins = "http://localhost:3000,http://127.0.0.1:3000" if DEBUG else ""
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", _default_csrf_origins).split(",")
    if origin.strip()
]
LOGIN_URL = "/login"

# Sources switch independently (FR-A-12); production defaults to live/fail-closed.
_default_source_mode = "mock" if DEBUG else "live"
FW_MODE_PROJECT = os.environ.get("FW_MODE_PROJECT", _default_source_mode).lower()
FW_MODE_EVENTS = os.environ.get("FW_MODE_EVENTS", _default_source_mode).lower()
FW_MODE_HEDERA = os.environ.get("FW_MODE_HEDERA", _default_source_mode).lower()
FW_HEDERA_NETWORK = os.environ.get("FW_HEDERA_NETWORK", "testnet").lower()
FW_HEDERA_MIRROR_NODE_URL = os.environ.get("FW_HEDERA_MIRROR_NODE_URL", "")
FW_HEDERA_PROJECT_REFERENCES = os.environ.get("FW_HEDERA_PROJECT_REFERENCES", "{}")
FW_HEDERA_TIMEOUT_SECONDS = float(os.environ.get("FW_HEDERA_TIMEOUT_SECONDS", "5"))
FW_HEDERA_MAX_PAGES = int(os.environ.get("FW_HEDERA_MAX_PAGES", "3"))
FW_HEDERA_CACHE_SECONDS = int(os.environ.get("FW_HEDERA_CACHE_SECONDS", "15"))
FW_HEDERA_DEMO_OPERATOR_ACCOUNT_ID = os.environ.get("FW_HEDERA_DEMO_OPERATOR_ACCOUNT_ID", "")
FW_HEDERA_DEMO_OPERATOR_PRIVATE_KEY = os.environ.get("FW_HEDERA_DEMO_OPERATOR_PRIVATE_KEY", "")
FW_HEDERA_DEMO_RECIPIENT_ACCOUNT_ID = os.environ.get("FW_HEDERA_DEMO_RECIPIENT_ACCOUNT_ID", "")
FW_MODE_SETTLEMENT = os.environ.get("FW_MODE_SETTLEMENT", "local").lower()
FW_MODE_EVIDENCE = os.environ.get("FW_MODE_EVIDENCE", "local").lower()
FW_GITHUB_TOKEN = os.environ.get("FW_GITHUB_TOKEN", "")
FW_GITHUB_ALLOWED_REPOSITORIES = {
    repository.strip().lower()
    for repository in os.environ.get("FW_GITHUB_ALLOWED_REPOSITORIES", "").split(",")
    if repository.strip()
}
FW_INGEST_AUTH_REQUIRED = os.environ.get("FW_INGEST_AUTH_REQUIRED", "false" if DEBUG else "true").lower() == "true"

# Format: producer-a:secret-a,producer-b:secret-b. Store secrets in the host
# secret manager/environment, never in source control. Production fails closed.
FW_INGEST_API_KEYS = {}
for _entry in os.environ.get("FW_INGEST_API_KEYS", "").split(","):
    if ":" in _entry:
        _producer, _key = _entry.split(":", 1)
        if _producer.strip() and _key:
            FW_INGEST_API_KEYS[_producer.strip()] = _key

# Operator credentials are never accepted from project rows; identity comes only
# from these configured credentials and the matching X-Operator-ID header.
FW_OPERATOR_API_KEYS = {}
for _entry in os.environ.get("FW_OPERATOR_API_KEYS", "").split(","):
    if ":" in _entry:
        _operator, _key = _entry.split(":", 1)
        if _operator.strip() and _key:
            FW_OPERATOR_API_KEYS[_operator.strip()] = _key
