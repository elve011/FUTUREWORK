import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BASE_DIR.parent
load_dotenv(BASE_DIR / ".env")  # HEDERA_*, GITHUB_*, FW_MODE_* ... (also inherited by the Node bridge)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.getenv("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")
APPEND_SLASH = False  # spec endpoints have no trailing slash

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "rest_framework",
    "corsheaders",
    "evidence",
    "githubint",
    "hcs",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"
CORS_ALLOW_ALL_ORIGINS = True  # hackathon; frontend on :3002

_db = dj_database_url.parse(os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"))
if "postgresql" in _db["ENGINE"]:
    # one PostgreSQL schema per module (fw_evidence for Dev 2)
    _db.setdefault("OPTIONS", {})["options"] = f"-c search_path={os.getenv('DB_SCHEMA', 'fw_evidence')},public"
DATABASES = {"default": _db}

REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "common.errors.handler",
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": None,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}

# ---------------- FUTUREWORK ----------------
FW_MODE = os.getenv("FW_MODE", "mock")  # per-source override: FW_MODE_<NAME>
HEDERA_NETWORK = os.getenv("HEDERA_NETWORK", "testnet")
MIRROR_NODE_URL = os.getenv("MIRROR_NODE_URL", "https://testnet.mirrornode.hedera.com")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "dev-secret")
PROJECT_API_URL = os.getenv("PROJECT_API_URL", "http://localhost:8001")
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:8004")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")

AUTO_VERIFY = os.getenv("AUTO_VERIFY", "1") == "1"
COMPLIANCE_THRESHOLD = int(os.getenv("COMPLIANCE_THRESHOLD", "60"))
HCS_MAX_RETRIES = 3
HCS_RETRY_DELAY = 1.0          # seconds, multiplied by attempt number
HCS_MAX_MESSAGE_BYTES = 900    # HCS limit is ~1 KB: anchor hashes + ids only
MIRROR_POLL_ATTEMPTS = 5
MIRROR_POLL_DELAY = 1.5
HEDERA_KEY_TYPE = os.getenv("HEDERA_KEY_TYPE", "der")  # der | ecdsa | ed25519
HCS_BRIDGE_DIR = REPO_ROOT / "hcs_bridge"
FIXTURES_DIR = REPO_ROOT / "contracts" / "fixtures" / "github"
