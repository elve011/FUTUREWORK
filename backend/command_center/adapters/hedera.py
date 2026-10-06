"""Read-only Hedera Mirror Node observer."""

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache


class HederaObserverUnavailable(Exception):
    """The Mirror Node could not provide a trustworthy observation."""


class MirrorNodeObserver:
    NETWORK_URLS = {
        "testnet": "https://testnet.mirrornode.hedera.com/api/v1",
        "mainnet": "https://mainnet-public.mirrornode.hedera.com/api/v1",
    }
    ENTITY_ID_RE = re.compile(r"^\d+\.\d+\.\d+$")
    MAX_RESPONSE_BYTES = 2_000_000
    REQUEST_BUDGET_SECONDS = 30

    def __init__(self):
        self.network = settings.FW_HEDERA_NETWORK
        if self.network not in self.NETWORK_URLS:
            raise HederaObserverUnavailable("HEDERA_NETWORK_UNSUPPORTED")
        base_url = getattr(settings, "FW_HEDERA_MIRROR_NODE_URL", "") or self.NETWORK_URLS[self.network]
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path.rstrip("/") != "/api/v1"
            or parsed.query
            or parsed.fragment
            or (self.network == "testnet" and "mainnet" in parsed.netloc.lower())
            or (self.network == "mainnet" and "testnet" in parsed.netloc.lower())
        ):
            raise HederaObserverUnavailable("HEDERA_MIRROR_NODE_URL_INVALID")
        self.base_url = base_url.rstrip("/")
        self.timeout = max(0.1, min(float(settings.FW_HEDERA_TIMEOUT_SECONDS), 30))
        self.max_pages = max(1, min(int(settings.FW_HEDERA_MAX_PAGES), 10))
        self.cache_seconds = max(0, min(int(settings.FW_HEDERA_CACHE_SECONDS), 60))
        self.deadline = None
        try:
            references = settings.FW_HEDERA_PROJECT_REFERENCES
            self.project_references = json.loads(references) if isinstance(references, str) else references
        except (TypeError, json.JSONDecodeError) as exc:
            raise HederaObserverUnavailable("HEDERA_PROJECT_REFERENCES_INVALID") from exc
        if not isinstance(self.project_references, dict):
            raise HederaObserverUnavailable("HEDERA_PROJECT_REFERENCES_INVALID")

    @property
    def source(self):
        return "hedera-mirror-node"

    def _references(self, project_id):
        references = self.project_references.get(project_id, {})
        if not isinstance(references, dict):
            raise HederaObserverUnavailable("HEDERA_PROJECT_REFERENCES_INVALID")
        normalized = {}
        keys = ("account_ids", "topic_ids", "token_ids", "contract_ids")
        if set(references) - set(keys):
            raise HederaObserverUnavailable("HEDERA_PROJECT_REFERENCES_INVALID")
        for key in keys:
            values = references.get(key, [])
            if not isinstance(values, list) or len(values) > 20 or any(
                not isinstance(value, str) or not self.ENTITY_ID_RE.fullmatch(value) for value in values
            ):
                raise HederaObserverUnavailable("HEDERA_PROJECT_REFERENCES_INVALID")
            normalized[key] = list(dict.fromkeys(values))
        return normalized

    def is_configured(self, project_id):
        references = self._references(project_id)
        return any(references.values())

    def _request_json(self, url):
        parsed_url = urlsplit(url)
        parsed_base = urlsplit(self.base_url)
        if parsed_url.scheme != "https" or parsed_url.netloc != parsed_base.netloc or not parsed_url.path.startswith(parsed_base.path + "/"):
            raise HederaObserverUnavailable("HEDERA_PAGINATION_URL_INVALID")
        cache_key = "hedera-mirror:" + hashlib.sha256(f"{self.network}:{url}".encode()).hexdigest()
        if self.cache_seconds:
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
        last_error = "HEDERA_SOURCE_UNAVAILABLE"
        for attempt in range(2):
            remaining = self.deadline - time.monotonic() if self.deadline is not None else self.timeout
            if remaining <= 0:
                raise HederaObserverUnavailable("HEDERA_REQUEST_BUDGET_EXCEEDED")
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "FUTUREWORK-HederaObserver/1.0"})
            try:
                with urlopen(request, timeout=min(self.timeout, remaining)) as response:
                    body = response.read(self.MAX_RESPONSE_BYTES + 1)
                if len(body) > self.MAX_RESPONSE_BYTES:
                    raise HederaObserverUnavailable("HEDERA_RESPONSE_TOO_LARGE")
                result = json.loads(body.decode("utf-8"))
                if not isinstance(result, dict):
                    raise HederaObserverUnavailable("HEDERA_RESPONSE_INVALID")
                if self.cache_seconds:
                    cache.set(cache_key, result, self.cache_seconds)
                return result
            except HTTPError as exc:
                last_error = "HEDERA_SOURCE_RATE_LIMITED" if exc.code == 429 else f"HEDERA_SOURCE_HTTP_{exc.code}"
                if attempt == 1 or (exc.code != 429 and exc.code < 500):
                    break
            except (URLError, TimeoutError, OSError, json.JSONDecodeError):
                if attempt == 1:
                    break
        raise HederaObserverUnavailable(last_error)

    def _pages(self, path, params=None):
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urlencode(params)
        rows = []
        for _ in range(self.max_pages):
            response = self._request_json(url)
            values = response.get("transactions", response.get("messages", response.get("tokens", response.get("contracts", []))))
            if not isinstance(values, list):
                raise HederaObserverUnavailable("HEDERA_RESPONSE_INVALID")
            rows.extend(values)
            next_link = ((response.get("links") or {}).get("next")) if isinstance(response.get("links"), dict) else None
            if not next_link:
                return rows
            url = urljoin(url, next_link)
        raise HederaObserverUnavailable("HEDERA_PAGINATION_LIMIT_REACHED")

    def _entity(self, path):
        response = self._request_json(f"{self.base_url}{path}")
        return response

    def _hashscan(self, kind, identifier):
        return f"https://hashscan.io/{self.network}/{kind}/{quote(identifier, safe='.-@')}"

    @staticmethod
    def _timestamp(value):
        if not value:
            return None
        try:
            whole, dot, fraction = str(value).partition(".")
            if not whole.isdigit() or (dot and (not fraction.isdigit() or len(fraction) > 9)):
                return None
            instant = datetime.fromtimestamp(int(whole), tz=timezone.utc)
            nanoseconds = fraction.ljust(9, "0") if dot else "000000000"
            return instant.strftime("%Y-%m-%dT%H:%M:%S") + f".{nanoseconds}Z"
        except (ValueError, OverflowError, OSError):
            return None

    def get_transactions(self, project_id):
        self.deadline = time.monotonic() + self.REQUEST_BUDGET_SECONDS
        references = self._references(project_id)
        transactions = []
        for account_id in references["account_ids"]:
            rows = self._pages("/transactions", {"account.id": f"eq:{account_id}", "order": "desc", "limit": "100"})
            for row in rows:
                transaction_id = row.get("transaction_id")
                if not transaction_id:
                    continue
                consensus_timestamp = self._timestamp(row.get("consensus_timestamp"))
                result = str(row.get("result") or "UNKNOWN").upper()
                transactions.append({
                    "transaction_id": transaction_id,
                    "kind": str(row.get("name") or "UNKNOWN").upper(),
                    "status": result,
                    "consensus_timestamp": consensus_timestamp,
                    "hashscan_url": self._hashscan("transaction", transaction_id.replace("@", "-", 1)),
                    "source": self.source,
                    "network": self.network,
                })
        unique = {row["transaction_id"]: row for row in transactions}
        return sorted(unique.values(), key=lambda item: item["consensus_timestamp"] or "", reverse=True)

    def get_activity(self, project_id):
        self.deadline = time.monotonic() + self.REQUEST_BUDGET_SECONDS
        references = self._references(project_id)
        activity = []
        for topic_id in references["topic_ids"]:
            rows = self._pages(f"/topics/{topic_id}/messages", {"order": "desc", "limit": "100"})
            for row in rows:
                timestamp = self._timestamp(row.get("consensus_timestamp"))
                activity.append({
                    "id": f"{topic_id}:{row.get('sequence_number', '')}",
                    "kind": "HCS_MESSAGE",
                    "topic_id": topic_id,
                    "consensus_timestamp": timestamp,
                    "summary": f"Topic message #{row.get('sequence_number', 'unknown')} observed",
                    "hashscan_url": self._hashscan("topic", topic_id),
                    "source": self.source,
                    "network": self.network,
                })
        for kind, key in (("token", "token_ids"), ("contract", "contract_ids")):
            for entity_id in references[key]:
                detail = self._entity(f"/{kind}s/{entity_id}")
                activity.append({
                    "id": f"{kind}:{entity_id}",
                    "kind": "HTS_TOKEN" if kind == "token" else "SMART_CONTRACT",
                    f"{kind}_id": entity_id,
                    "consensus_timestamp": None,
                    "summary": detail.get("name") or detail.get("memo") or f"Configured {kind} observed",
                    "hashscan_url": self._hashscan(kind, entity_id),
                    "source": self.source,
                    "network": self.network,
                })
        return activity
