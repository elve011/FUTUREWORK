import pytest


@pytest.fixture(autouse=True)
def _env(settings, monkeypatch):
    from ports.mock import LEDGER, PUBLISHED

    monkeypatch.setenv("FW_MODE", "mock")
    for name in ("PROJECT", "HCS", "MIRROR", "EVENTS", "LLM", "GITHUB"):
        monkeypatch.delenv(f"FW_MODE_{name}", raising=False)
    settings.GITHUB_WEBHOOK_SECRET = "test-secret"
    settings.AUTO_VERIFY = True
    settings.MIRROR_POLL_DELAY = 0
    settings.HCS_RETRY_DELAY = 0
    LEDGER.reset()
    PUBLISHED.clear()


@pytest.fixture
def client():
    from rest_framework.test import APIClient
    return APIClient()
