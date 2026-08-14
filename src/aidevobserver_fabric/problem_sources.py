"""Bounded, policy-aware intake adapters for public business-friction sources.

The module deliberately stops at candidate observations.  A public complaint,
issue, or forum post is evidence that a problem may exist; it is not authority
to execute code or a claim that the observation is universally true.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import socket
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib import error, parse, request
from xml.etree import ElementTree


DEFAULT_USER_AGENT = "AIDevObserver-ProblemDiscovery/0.1"
_SECRET_QUERY_KEYS = frozenset(
    {"access_token", "api_key", "apikey", "auth", "authorization", "key", "token"}
)
_SECRET_HEADER_NAMES = frozenset(
    {"authorization", "cookie", "proxy-authorization", "set-cookie", "x-api-key"}
)
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?x)(?<!\w)(?:\+?1[\s.()-]*)?(?:\(?\d{3}\)?[\s.-]*)\d{3}[\s.-]*\d{4}(?!\w)"
)
_HANDLE_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,38}\b")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


class AccessClass(str, Enum):
    """Source access and reuse posture.

    GREEN sources expose a first-party public API/feed with clear reuse terms.
    AMBER sources expose an official machine interface but user-content rights
    vary, so only minimized excerpts and derived metadata should be retained.
    RED sources are disabled and must not be fetched by this runtime.
    """

    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    access_class: AccessClass
    max_bytes: int = 1_000_000
    timeout_seconds: float = 12.0
    max_records: int = 100
    excerpt_chars: int = 320
    content_policy: str = "metadata_short_excerpt_and_derived_facts"
    candidate_only: bool = True
    allow_network: bool = True
    pii_minimized: bool = True

    def __post_init__(self) -> None:
        if self.max_bytes < 1 or self.max_bytes > 10_000_000:
            raise ValueError("max_bytes must be between 1 and 10,000,000")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("timeout_seconds must be between 0 and 60")
        if self.max_records < 1 or self.max_records > 1_000:
            raise ValueError("max_records must be between 1 and 1,000")
        if self.excerpt_chars < 40 or self.excerpt_chars > 2_000:
            raise ValueError("excerpt_chars must be between 40 and 2,000")
        if not self.candidate_only:
            raise ValueError("problem discovery sources must remain candidate_only")

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["access_class"] = self.access_class.value
        return row


@dataclass(frozen=True, slots=True)
class SourceSpec:
    source_id: str
    name: str
    adapter: str
    endpoint: str
    fixed_hosts: tuple[str, ...]
    policy: SourcePolicy
    cadence_seconds: int
    docs_url: str | None = None
    terms_url: str | None = None
    default_headers: Mapping[str, str] = field(default_factory=dict)
    auth_env: str | None = field(default=None, repr=False, compare=False)
    auth_header: str | None = field(default=None, repr=False, compare=False)
    auth_prefix: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.source_id or not self.adapter:
            raise ValueError("source_id and adapter are required")
        if self.cadence_seconds < 60:
            raise ValueError("cadence_seconds must be at least 60")
        hosts = tuple(host.lower().rstrip(".") for host in self.fixed_hosts)
        if not hosts or any(not host or "/" in host or ":" in host for host in hosts):
            raise ValueError("fixed_hosts must contain host names only")
        object.__setattr__(self, "fixed_hosts", hosts)
        endpoint = parse.urlsplit(self.endpoint)
        endpoint_host = (endpoint.hostname or "").lower().rstrip(".")
        if endpoint.scheme != "https":
            raise ValueError("source URL must use https")
        if endpoint.username or endpoint.password:
            raise ValueError("source URL must not include userinfo")
        if endpoint.port not in (None, 443):
            raise ValueError("source URL must use the default HTTPS port")
        if endpoint_host not in hosts:
            raise ValueError(f"host {endpoint_host!r} is outside fixed_hosts")
        if bool(self.auth_env) != bool(self.auth_header):
            raise ValueError("auth_env and auth_header must be configured together")
        secret_headers = {
            str(name).lower() for name in self.default_headers
        } & _SECRET_HEADER_NAMES
        if secret_headers:
            raise ValueError(
                "credential-bearing default_headers are forbidden; use auth_env/auth_header"
            )
        if self.policy.access_class is AccessClass.RED and self.policy.allow_network:
            raise ValueError("RED sources cannot enable network access")

    def to_dict(self) -> dict[str, Any]:
        """Serialize public configuration without auth environment details."""

        return {
            "source_id": self.source_id,
            "name": self.name,
            "adapter": self.adapter,
            "endpoint": _sanitize_url(self.endpoint),
            "fixed_hosts": list(self.fixed_hosts),
            "policy": self.policy.to_dict(),
            "cadence_seconds": self.cadence_seconds,
            "docs_url": self.docs_url,
            "terms_url": self.terms_url,
            "default_headers": {
                str(key): str(value)
                for key, value in self.default_headers.items()
                if str(key).lower() not in _SECRET_HEADER_NAMES
            },
            "auth_configured": bool(self.auth_env),
        }


@dataclass(frozen=True, slots=True)
class NormalizedObservation:
    source_id: str
    observation_id: str
    kind: str
    source_url: str
    title: str
    excerpt: str | None
    published_at: str | None
    metadata: Mapping[str, Any]
    raw_digest: str
    candidate_only: bool = True
    serves_truth: bool = False

    def __post_init__(self) -> None:
        if not self.candidate_only or self.serves_truth:
            raise ValueError("normalized source observations are candidate-only")
        if not self.raw_digest.startswith("sha256:"):
            raise ValueError("raw_digest must be a sha256 digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "observation_id": self.observation_id,
            "kind": self.kind,
            "source_url": _sanitize_url(self.source_url),
            "title": self.title,
            "excerpt": self.excerpt,
            "published_at": self.published_at,
            "metadata": _json_safe(self.metadata),
            "raw_digest": self.raw_digest,
            "candidate_only": True,
            "serves_truth": False,
        }


@dataclass(frozen=True, slots=True)
class FetchResult:
    source_id: str
    request_url: str
    final_url: str | None
    fetched_at: str
    ok: bool
    status_code: int | None
    content_type: str | None
    body_digest: str | None
    body_size: int
    elapsed_ms: float
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    from_fixture: bool = False
    observations: tuple[NormalizedObservation, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    _body: bytes = field(default=b"", repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a receipt; raw response bytes and auth headers are excluded."""

        return {
            "source_id": self.source_id,
            "request_url": _sanitize_url(self.request_url),
            "final_url": _sanitize_url(self.final_url) if self.final_url else None,
            "fetched_at": self.fetched_at,
            "ok": self.ok,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "body_digest": self.body_digest,
            "body_size": self.body_size,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "etag": self.etag,
            "last_modified": self.last_modified,
            "not_modified": self.not_modified,
            "from_fixture": self.from_fixture,
            "observations": [row.to_dict() for row in self.observations],
            "error_code": self.error_code,
            "error_message": self.error_message,
            "candidate_only": True,
            "serves_truth": False,
        }


GREEN = AccessClass.GREEN
AMBER = AccessClass.AMBER
RED = AccessClass.RED

_GREEN_POLICY = SourcePolicy(GREEN)
_AMBER_POLICY = SourcePolicy(AMBER, excerpt_chars=320)

DEFAULT_GITHUB_OPERATIONAL_REPOS: tuple[str, ...] = (
    "airbytehq/airbyte",
    "dolibarr/dolibarr",
    "frappe/erpnext",
    "metabase/metabase",
    "n8n-io/n8n",
    "odoo/odoo",
    "woocommerce/woocommerce",
)


DEFAULT_SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        source_id="github.operational_issues",
        name="GitHub operational software issues",
        adapter="github_issues",
        endpoint=(
            "https://api.github.com/search/issues"
            "?q=workaround+is%3Aissue+updated%3A%3E%3D2026-01-01"
            "+repo%3Afrappe%2Ferpnext&per_page=100"
        ),
        fixed_hosts=("api.github.com",),
        policy=_AMBER_POLICY,
        cadence_seconds=14_400,
        docs_url="https://docs.github.com/en/rest/search/search#search-issues-and-pull-requests",
        terms_url="https://docs.github.com/en/site-policy/github-terms/github-terms-of-service",
        default_headers={"Accept": "application/vnd.github+json"},
        auth_env="GITHUB_TOKEN",
        auth_header="Authorization",
        auth_prefix="Bearer ",
    ),
    SourceSpec(
        source_id="hn.ask",
        name="Hacker News Ask HN",
        adapter="hn_ask",
        endpoint="https://hacker-news.firebaseio.com/v0/askstories.json",
        fixed_hosts=("hacker-news.firebaseio.com",),
        policy=_AMBER_POLICY,
        cadence_seconds=900,
        docs_url="https://github.com/HackerNews/API",
    ),
    SourceSpec(
        source_id="stackexchange.workflow_questions",
        name="Stack Exchange workflow questions",
        adapter="stackexchange_questions",
        endpoint=(
            "https://api.stackexchange.com/2.3/search/advanced"
            "?site=stackoverflow&sort=activity&order=desc&q=manual%20process&pagesize=100"
        ),
        fixed_hosts=("api.stackexchange.com",),
        policy=_GREEN_POLICY,
        cadence_seconds=14_400,
        docs_url="https://api.stackexchange.com/docs/advanced-search",
        terms_url="https://stackoverflow.com/help/licensing",
    ),
    SourceSpec(
        source_id="discourse.frappe",
        name="Frappe and ERPNext community",
        adapter="rss",
        endpoint="https://discuss.frappe.io/latest.rss?order=created",
        fixed_hosts=("discuss.frappe.io",),
        policy=_AMBER_POLICY,
        cadence_seconds=1_800,
        docs_url="https://meta.discourse.org/t/finding-discourse-rss-feeds/264134",
    ),
    SourceSpec(
        source_id="discourse.n8n",
        name="n8n community",
        adapter="rss",
        endpoint="https://community.n8n.io/latest.rss?order=created",
        fixed_hosts=("community.n8n.io",),
        policy=_AMBER_POLICY,
        cadence_seconds=1_800,
        docs_url="https://meta.discourse.org/t/finding-discourse-rss-feeds/264134",
    ),
    SourceSpec(
        source_id="discourse.make",
        name="Make community",
        adapter="rss",
        endpoint="https://community.make.com/latest.rss?order=created",
        fixed_hosts=("community.make.com",),
        policy=_AMBER_POLICY,
        cadence_seconds=1_800,
        docs_url="https://meta.discourse.org/t/finding-discourse-rss-feeds/264134",
    ),
    SourceSpec(
        source_id="cfpb.complaints",
        name="CFPB Consumer Complaint Database",
        adapter="cfpb_complaints",
        endpoint=(
            "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
            "?field=complaint_what_happened&has_narrative=yes&size=100&sort=created_date_desc"
        ),
        fixed_hosts=("www.consumerfinance.gov",),
        policy=_GREEN_POLICY,
        cadence_seconds=86_400,
        docs_url="https://cfpb.github.io/ccdb5-api/",
    ),
    SourceSpec(
        source_id="federalregister.business_friction",
        name="Federal Register business-friction notices",
        adapter="federal_register",
        endpoint=(
            "https://www.federalregister.gov/api/v1/documents.json"
            "?conditions%5Bterm%5D=small%20business%20burden&per_page=100&order=newest"
        ),
        fixed_hosts=("www.federalregister.gov",),
        policy=_GREEN_POLICY,
        cadence_seconds=86_400,
        docs_url="https://www.federalregister.gov/developers/documentation/api/v1",
    ),
)

DEFAULT_SOURCE_BY_ID: Mapping[str, SourceSpec] = {
    source.source_id: source for source in DEFAULT_SOURCE_SPECS
}

SUPPORTED_ADAPTERS = frozenset(
    {
        "github_issues",
        "hn_ask",
        "stackexchange_questions",
        "rss",
        "cfpb_complaints",
        "federal_register",
    }
)


def source_spec_from_dict(value: Mapping[str, Any]) -> SourceSpec:
    """Load a validated connector without accepting credential values."""

    policy_value = value.get("policy") or {}
    if not isinstance(policy_value, Mapping):
        raise TypeError("source policy must be an object")
    access_value = policy_value.get("access_class", value.get("access_class", "AMBER"))
    try:
        access_class = AccessClass(str(access_value).upper())
    except ValueError as exc:
        raise ValueError(f"unsupported access class: {access_value}") from exc
    policy_fields = {
        key: policy_value[key]
        for key in (
            "max_bytes",
            "timeout_seconds",
            "max_records",
            "excerpt_chars",
            "content_policy",
            "candidate_only",
            "allow_network",
            "pii_minimized",
        )
        if key in policy_value
    }
    policy = SourcePolicy(access_class=access_class, **policy_fields)
    adapter = str(value.get("adapter") or "")
    if adapter not in SUPPORTED_ADAPTERS:
        raise ValueError(f"unsupported source adapter: {adapter}")
    headers = value.get("default_headers") or {}
    if not isinstance(headers, Mapping):
        raise TypeError("default_headers must be an object")
    fixed_hosts = value.get("fixed_hosts") or ()
    if not isinstance(fixed_hosts, (list, tuple)):
        raise TypeError("fixed_hosts must be an array")
    return SourceSpec(
        source_id=str(value.get("source_id") or ""),
        name=str(value.get("name") or value.get("source_id") or ""),
        adapter=adapter,
        endpoint=str(value.get("endpoint") or ""),
        fixed_hosts=tuple(str(host) for host in fixed_hosts),
        policy=policy,
        cadence_seconds=int(value.get("cadence_seconds", 3_600)),
        docs_url=str(value["docs_url"]) if value.get("docs_url") else None,
        terms_url=str(value["terms_url"]) if value.get("terms_url") else None,
        default_headers={str(key): str(item) for key, item in headers.items()},
        auth_env=str(value["auth_env"]) if value.get("auth_env") else None,
        auth_header=str(value["auth_header"]) if value.get("auth_header") else None,
        auth_prefix=str(value.get("auth_prefix") or ""),
    )


def load_source_specs(path: Path) -> tuple[SourceSpec, ...]:
    """Load a complete, policy-reviewed source portfolio from JSON."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("sources") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        raise ValueError("source config must be an array or an object with a sources array")
    sources = tuple(source_spec_from_dict(row) for row in rows if isinstance(row, Mapping))
    if len(sources) != len(rows):
        raise ValueError("every source config row must be an object")
    ids = [source.source_id for source in sources]
    if len(set(ids)) != len(ids):
        raise ValueError("source IDs must be unique")
    return sources


class _FixedHostRedirectHandler(request.HTTPRedirectHandler):
    def __init__(self, source: SourceSpec) -> None:
        self.source = source

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        try:
            _validate_source_url(self.source, newurl)
        except ValueError as exc:
            raise error.URLError(f"redirect rejected: {exc}") from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_source_url(source: SourceSpec, url: str) -> None:
    parsed = parse.urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https":
        raise ValueError("source URL must use https")
    if parsed.username or parsed.password:
        raise ValueError("source URL must not include userinfo")
    if parsed.port not in (None, 443):
        raise ValueError("source URL must use the default HTTPS port")
    if host not in source.fixed_hosts:
        raise ValueError(f"host {host!r} is outside fixed_hosts")


def _sanitize_url(url: str | None) -> str:
    if not url:
        return ""
    parts = parse.urlsplit(url)
    query = parse.parse_qsl(parts.query, keep_blank_values=True)
    safe_query = [
        (key, "REDACTED" if key.lower() in _SECRET_QUERY_KEYS else value)
        for key, value in query
    ]
    return parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, parse.urlencode(safe_query, doseq=True), "")
    )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


def _plain_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(_HTML_TAG_RE.sub(" ", str(value)))
    return _SPACE_RE.sub(" ", text).strip()


def _minimize_text(value: Any, limit: int) -> str | None:
    text = _plain_text(value)
    if not text:
        return None
    text = _EMAIL_RE.sub("[email redacted]", text)
    text = _PHONE_RE.sub("[phone redacted]", text)
    text = _HANDLE_RE.sub("[handle redacted]", text)
    text = _SPACE_RE.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _safe_title(value: Any, limit: int = 180) -> str:
    return _minimize_text(value, limit) or "Untitled observation"


def _record_digest(record: Any) -> str:
    try:
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode()
    except (TypeError, ValueError):
        payload = repr(record).encode("utf-8", errors="replace")
    return _sha256(payload)


def _observation_id(source_id: str, *parts: Any) -> str:
    raw = "\x1f".join(str(part) for part in parts if part not in (None, ""))
    return f"{source_id}:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def _response_header(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    if hasattr(headers, "get"):
        value = headers.get(name)
        return str(value) if value is not None else None
    return None


def replay_fetch_result(
    source: SourceSpec,
    fixture: bytes | str | Mapping[str, Any] | list[Any] | Path,
    *,
    content_type: str | None = None,
    request_url: str | None = None,
    fetched_at: str | None = None,
) -> FetchResult:
    """Create a deterministic fetch receipt from a fixture or captured response."""

    url = request_url or source.endpoint
    try:
        _validate_source_url(source, url)
    except ValueError as exc:
        return _failure(source, url, "url_policy_error", str(exc), from_fixture=True)
    try:
        if isinstance(fixture, Path):
            body = fixture.read_bytes()
        elif isinstance(fixture, bytes):
            body = fixture
        elif isinstance(fixture, str):
            body = fixture.encode("utf-8")
        else:
            body = json.dumps(fixture, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (OSError, TypeError, ValueError) as exc:
        return _failure(source, url, "fixture_error", str(exc), from_fixture=True)
    if len(body) > source.policy.max_bytes:
        return _failure(
            source,
            url,
            "response_too_large",
            f"fixture exceeds max_bytes={source.policy.max_bytes}",
            from_fixture=True,
            body_size=len(body),
        )
    if content_type is None:
        content_type = "application/rss+xml" if source.adapter == "rss" else "application/json"
    return FetchResult(
        source_id=source.source_id,
        request_url=_sanitize_url(url),
        final_url=_sanitize_url(url),
        fetched_at=fetched_at or _utc_now(),
        ok=True,
        status_code=200,
        content_type=content_type,
        body_digest=_sha256(body),
        body_size=len(body),
        elapsed_ms=0.0,
        from_fixture=True,
        _body=body,
    )


def _failure(
    source: SourceSpec,
    url: str,
    code: str,
    message: str,
    *,
    status_code: int | None = None,
    elapsed_ms: float = 0.0,
    from_fixture: bool = False,
    body_size: int = 0,
) -> FetchResult:
    return FetchResult(
        source_id=source.source_id,
        request_url=_sanitize_url(url),
        final_url=None,
        fetched_at=_utc_now(),
        ok=False,
        status_code=status_code,
        content_type=None,
        body_digest=None,
        body_size=body_size,
        elapsed_ms=elapsed_ms,
        from_fixture=from_fixture,
        error_code=code,
        error_message=_minimize_text(message, 300),
    )


def fetch_source(
    source: SourceSpec,
    *,
    request_url: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    fixture: bytes | str | Mapping[str, Any] | list[Any] | Path | None = None,
    opener: Any | None = None,
) -> FetchResult:
    """Fetch one source through a bounded, fixed-host HTTPS request.

    ``fixture`` bypasses the network and is intended for tests, deterministic
    replays, and captured-response regression suites.
    """

    if fixture is not None:
        return replay_fetch_result(source, fixture, request_url=request_url)

    url = request_url or source.endpoint
    if source.policy.access_class is AccessClass.RED or not source.policy.allow_network:
        return _failure(source, url, "source_disabled", "source policy disables network access")
    try:
        _validate_source_url(source, url)
    except ValueError as exc:
        return _failure(source, url, "url_policy_error", str(exc))

    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept-Encoding": "identity"}
    headers.update({str(key): str(value) for key, value in source.default_headers.items()})
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    if source.auth_env and source.auth_header:
        secret = os.environ.get(source.auth_env)
        if secret:
            headers[source.auth_header] = f"{source.auth_prefix}{secret}"

    req = request.Request(url, headers=headers, method="GET")
    client = opener or request.build_opener(_FixedHostRedirectHandler(source))
    started = time.monotonic()
    try:
        with client.open(req, timeout=source.policy.timeout_seconds) as response:
            status = int(getattr(response, "status", response.getcode()))
            final_url = str(response.geturl())
            _validate_source_url(source, final_url)
            response_headers = getattr(response, "headers", None)
            content_length = _response_header(response_headers, "Content-Length")
            if content_length:
                try:
                    if int(content_length) > source.policy.max_bytes:
                        return _failure(
                            source,
                            url,
                            "response_too_large",
                            f"Content-Length exceeds max_bytes={source.policy.max_bytes}",
                            status_code=status,
                            elapsed_ms=(time.monotonic() - started) * 1000,
                        )
                except ValueError:
                    pass
            body = response.read(source.policy.max_bytes + 1)
            elapsed = (time.monotonic() - started) * 1000
            if len(body) > source.policy.max_bytes:
                return _failure(
                    source,
                    url,
                    "response_too_large",
                    f"response exceeds max_bytes={source.policy.max_bytes}",
                    status_code=status,
                    elapsed_ms=elapsed,
                    body_size=len(body),
                )
            return FetchResult(
                source_id=source.source_id,
                request_url=_sanitize_url(url),
                final_url=_sanitize_url(final_url),
                fetched_at=_utc_now(),
                ok=200 <= status < 300,
                status_code=status,
                content_type=_response_header(response_headers, "Content-Type"),
                body_digest=_sha256(body),
                body_size=len(body),
                elapsed_ms=elapsed,
                etag=_response_header(response_headers, "ETag"),
                last_modified=_response_header(response_headers, "Last-Modified"),
                _body=body,
                error_code=None if 200 <= status < 300 else "http_error",
                error_message=None if 200 <= status < 300 else f"HTTP status {status}",
            )
    except error.HTTPError as exc:
        elapsed = (time.monotonic() - started) * 1000
        if exc.code == 304:
            return FetchResult(
                source_id=source.source_id,
                request_url=_sanitize_url(url),
                final_url=_sanitize_url(exc.geturl() or url),
                fetched_at=_utc_now(),
                ok=True,
                status_code=304,
                content_type=_response_header(exc.headers, "Content-Type"),
                body_digest=None,
                body_size=0,
                elapsed_ms=elapsed,
                etag=_response_header(exc.headers, "ETag") or etag,
                last_modified=_response_header(exc.headers, "Last-Modified") or last_modified,
                not_modified=True,
            )
        return _failure(
            source,
            url,
            "http_error",
            f"HTTP status {exc.code}: {exc.reason}",
            status_code=exc.code,
            elapsed_ms=elapsed,
        )
    except (error.URLError, TimeoutError, socket.timeout) as exc:
        return _failure(
            source,
            url,
            "network_error",
            str(getattr(exc, "reason", exc)),
            elapsed_ms=(time.monotonic() - started) * 1000,
        )
    except (OSError, ValueError) as exc:
        return _failure(
            source,
            url,
            "fetch_error",
            str(exc),
            elapsed_ms=(time.monotonic() - started) * 1000,
        )


def _build_observation(
    source: SourceSpec,
    *,
    stable_parts: Iterable[Any],
    kind: str,
    source_url: str,
    title: Any,
    excerpt: Any,
    published_at: Any,
    metadata: Mapping[str, Any],
    raw: Any,
) -> NormalizedObservation:
    return NormalizedObservation(
        source_id=source.source_id,
        observation_id=_observation_id(source.source_id, *stable_parts),
        kind=kind,
        source_url=_sanitize_url(source_url or source.endpoint),
        title=_safe_title(title),
        excerpt=_minimize_text(excerpt, source.policy.excerpt_chars),
        published_at=str(published_at) if published_at not in (None, "") else None,
        metadata=_json_safe(metadata),
        raw_digest=_record_digest(raw),
    )


def _github_observations(source: SourceSpec, payload: Any) -> list[NormalizedObservation]:
    records = payload.get("items", []) if isinstance(payload, Mapping) else []
    rows: list[NormalizedObservation] = []
    for record in records[: source.policy.max_records]:
        if not isinstance(record, Mapping) or record.get("pull_request"):
            continue
        repo_url = str(record.get("repository_url") or "")
        repo = repo_url.split("/repos/", 1)[-1] if "/repos/" in repo_url else None
        labels = [
            str(label.get("name"))
            for label in record.get("labels", [])[:10]
            if isinstance(label, Mapping) and label.get("name")
        ]
        reactions = record.get("reactions") if isinstance(record.get("reactions"), Mapping) else {}
        rows.append(
            _build_observation(
                source,
                stable_parts=(record.get("node_id"), record.get("id"), repo, record.get("number")),
                kind="software_issue",
                source_url=str(record.get("html_url") or source.endpoint),
                title=record.get("title"),
                excerpt=record.get("body"),
                published_at=record.get("created_at"),
                metadata={
                    "repository": repo,
                    "issue_number": record.get("number"),
                    "state": record.get("state"),
                    "labels": labels,
                    "comment_count": record.get("comments"),
                    "reactions_total": reactions.get("total_count"),
                    "created_at": record.get("created_at"),
                    "updated_at": record.get("updated_at"),
                    "closed_at": record.get("closed_at"),
                },
                raw=record,
            )
        )
    return rows


def _hn_observations(source: SourceSpec, payload: Any) -> list[NormalizedObservation]:
    if isinstance(payload, list) and all(isinstance(item, int) for item in payload):
        return [
            _build_observation(
                source,
                stable_parts=(item_id,),
                kind="hn_ask_reference",
                source_url=f"https://news.ycombinator.com/item?id={item_id}",
                title=f"Ask HN item {item_id}",
                excerpt=None,
                published_at=None,
                metadata={"item_id": item_id, "needs_item_fetch": True},
                raw=item_id,
            )
            for item_id in payload[: source.policy.max_records]
        ]
    if isinstance(payload, Mapping) and isinstance(payload.get("items"), list):
        records = payload["items"]
    elif isinstance(payload, list):
        records = payload
    elif isinstance(payload, Mapping):
        records = [payload]
    else:
        records = []
    rows: list[NormalizedObservation] = []
    for record in records[: source.policy.max_records]:
        if not isinstance(record, Mapping) or not record.get("id"):
            continue
        item_id = record["id"]
        rows.append(
            _build_observation(
                source,
                stable_parts=(item_id,),
                kind="hn_ask",
                source_url=f"https://news.ycombinator.com/item?id={item_id}",
                title=record.get("title"),
                excerpt=record.get("text"),
                published_at=record.get("time"),
                metadata={
                    "item_id": item_id,
                    "type": record.get("type"),
                    "score": record.get("score"),
                    "comment_count": record.get("descendants"),
                },
                raw=record,
            )
        )
    return rows


def _stackexchange_observations(source: SourceSpec, payload: Any) -> list[NormalizedObservation]:
    records = payload.get("items", []) if isinstance(payload, Mapping) else []
    rows: list[NormalizedObservation] = []
    for record in records[: source.policy.max_records]:
        if not isinstance(record, Mapping):
            continue
        question_id = record.get("question_id")
        rows.append(
            _build_observation(
                source,
                stable_parts=(question_id, record.get("link")),
                kind="technical_question",
                source_url=str(record.get("link") or source.endpoint),
                title=record.get("title"),
                excerpt=record.get("body") or record.get("body_markdown"),
                published_at=record.get("creation_date"),
                metadata={
                    "question_id": question_id,
                    "tags": [str(tag) for tag in record.get("tags", [])[:10]],
                    "score": record.get("score"),
                    "view_count": record.get("view_count"),
                    "answer_count": record.get("answer_count"),
                    "is_answered": record.get("is_answered"),
                    "accepted_answer_id": record.get("accepted_answer_id"),
                    "last_activity_date": record.get("last_activity_date"),
                },
                raw=record,
            )
        )
    return rows


def _cfpb_observations(source: SourceSpec, payload: Any) -> list[NormalizedObservation]:
    hits = payload.get("hits", {}) if isinstance(payload, Mapping) else {}
    records = hits.get("hits", []) if isinstance(hits, Mapping) else []
    rows: list[NormalizedObservation] = []
    for hit in records[: source.policy.max_records]:
        record = hit.get("_source", hit) if isinstance(hit, Mapping) else {}
        if not isinstance(record, Mapping):
            continue
        complaint_id = record.get("complaint_id")
        detail_url = (
            "https://www.consumerfinance.gov/data-research/consumer-complaints/"
            f"search/detail/{complaint_id}"
            if complaint_id
            else source.endpoint
        )
        title = " — ".join(
            str(value) for value in (record.get("product"), record.get("issue")) if value
        )
        rows.append(
            _build_observation(
                source,
                stable_parts=(complaint_id, hit.get("_id") if isinstance(hit, Mapping) else None),
                kind="consumer_complaint",
                source_url=detail_url,
                title=title or "Consumer complaint",
                excerpt=record.get("complaint_what_happened"),
                published_at=record.get("date_received"),
                metadata={
                    "complaint_id": complaint_id,
                    "product": record.get("product"),
                    "sub_product": record.get("sub_product"),
                    "issue": record.get("issue"),
                    "sub_issue": record.get("sub_issue"),
                    "company": record.get("company"),
                    "company_response": record.get("company_response"),
                    "timely": record.get("timely"),
                    "submitted_via": record.get("submitted_via"),
                    "state": record.get("state"),
                },
                raw=record,
            )
        )
    return rows


def _federal_register_observations(source: SourceSpec, payload: Any) -> list[NormalizedObservation]:
    records = payload.get("results", []) if isinstance(payload, Mapping) else []
    rows: list[NormalizedObservation] = []
    for record in records[: source.policy.max_records]:
        if not isinstance(record, Mapping):
            continue
        agencies = [
            str(agency.get("name"))
            for agency in record.get("agencies", [])[:10]
            if isinstance(agency, Mapping) and agency.get("name")
        ]
        rows.append(
            _build_observation(
                source,
                stable_parts=(record.get("document_number"), record.get("html_url")),
                kind="regulatory_document",
                source_url=str(record.get("html_url") or source.endpoint),
                title=record.get("title"),
                excerpt=record.get("abstract"),
                published_at=record.get("publication_date"),
                metadata={
                    "document_number": record.get("document_number"),
                    "document_type": record.get("type"),
                    "agencies": agencies,
                    "publication_date": record.get("publication_date"),
                    "comment_end_date": record.get("comments_close_on"),
                    "effective_on": record.get("effective_on"),
                    "docket_ids": [str(value) for value in record.get("docket_ids", [])[:10]],
                    "regulation_ids": [
                        str(value) for value in record.get("regulation_id_numbers", [])[:10]
                    ],
                    "pdf_url": _sanitize_url(str(record.get("pdf_url") or "")) or None,
                },
                raw=record,
            )
        )
    return rows


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ElementTree.Element, names: set[str]) -> str | None:
    for child in list(element):
        if _local_name(child.tag) in names:
            if _local_name(child.tag) == "link" and child.attrib.get("href"):
                return child.attrib["href"]
            return "".join(child.itertext()).strip()
    return None


def _rss_observations(source: SourceSpec, body: bytes) -> list[NormalizedObservation]:
    upper = body[:4_096].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("RSS fixture contains a forbidden DTD or entity declaration")
    root = ElementTree.fromstring(body)
    entries = [
        element
        for element in root.iter()
        if _local_name(element.tag) in {"item", "entry"}
    ]
    rows: list[NormalizedObservation] = []
    for entry in entries[: source.policy.max_records]:
        title = _child_text(entry, {"title"})
        link = _child_text(entry, {"link"}) or source.endpoint
        guid = _child_text(entry, {"guid", "id"})
        published = _child_text(entry, {"pubdate", "published", "updated"})
        content = _child_text(entry, {"description", "summary", "content", "encoded"})
        categories = [
            _plain_text("".join(child.itertext()))
            for child in list(entry)
            if _local_name(child.tag) in {"category", "tag"}
        ][:10]
        raw = ElementTree.tostring(entry, encoding="utf-8")
        rows.append(
            _build_observation(
                source,
                stable_parts=(guid, link, title),
                kind="forum_topic",
                source_url=link,
                title=title,
                excerpt=content,
                published_at=published,
                metadata={"categories": categories},
                raw=raw.decode("utf-8", errors="replace"),
            )
        )
    return rows


_JSON_ADAPTERS = {
    "github_issues": _github_observations,
    "hn_ask": _hn_observations,
    "stackexchange_questions": _stackexchange_observations,
    "cfpb_complaints": _cfpb_observations,
    "federal_register": _federal_register_observations,
}


def normalize_fetch_result(source: SourceSpec, result: FetchResult) -> FetchResult:
    """Parse a fetch receipt, retaining parse failures instead of raising them."""

    if result.source_id != source.source_id:
        return replace(
            result,
            ok=False,
            error_code="source_mismatch",
            error_message="fetch result source_id does not match source spec",
            observations=(),
        )
    if not result.ok or result.not_modified:
        return result
    try:
        if source.adapter == "rss":
            observations = _rss_observations(source, result._body)
        else:
            parser = _JSON_ADAPTERS.get(source.adapter)
            if parser is None:
                raise ValueError(f"unsupported source adapter: {source.adapter}")
            payload = json.loads(result._body.decode("utf-8"))
            observations = parser(source, payload)
        return replace(result, observations=tuple(observations))
    except (UnicodeDecodeError, json.JSONDecodeError, ElementTree.ParseError, ValueError, TypeError) as exc:
        return replace(
            result,
            ok=False,
            observations=(),
            error_code="parse_error",
            error_message=_minimize_text(str(exc), 300),
        )


def collect_source(
    source: SourceSpec,
    *,
    request_url: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    fixture: bytes | str | Mapping[str, Any] | list[Any] | Path | None = None,
    opener: Any | None = None,
) -> FetchResult:
    """Fetch and normalize one source without letting one source abort a loop."""

    result = fetch_source(
        source,
        request_url=request_url,
        etag=etag,
        last_modified=last_modified,
        fixture=fixture,
        opener=opener,
    )
    return normalize_fetch_result(source, result)


def collect_many(
    sources: Iterable[SourceSpec],
    *,
    fixtures: Mapping[str, bytes | str | Mapping[str, Any] | list[Any] | Path] | None = None,
) -> tuple[FetchResult, ...]:
    """Collect sources independently; failures are returned alongside successes."""

    fixture_map = fixtures or {}
    results: list[FetchResult] = []
    for source in sources:
        try:
            results.append(collect_source(source, fixture=fixture_map.get(source.source_id)))
        except Exception as exc:  # defensive boundary for long-running discovery loops
            results.append(_failure(source, source.endpoint, "unexpected_error", str(exc)))
    return tuple(results)


__all__ = [
    "AccessClass",
    "AMBER",
    "DEFAULT_GITHUB_OPERATIONAL_REPOS",
    "DEFAULT_SOURCE_BY_ID",
    "DEFAULT_SOURCE_SPECS",
    "FetchResult",
    "GREEN",
    "NormalizedObservation",
    "RED",
    "SourcePolicy",
    "SourceSpec",
    "SUPPORTED_ADAPTERS",
    "collect_many",
    "collect_source",
    "fetch_source",
    "load_source_specs",
    "normalize_fetch_result",
    "replay_fetch_result",
    "source_spec_from_dict",
]
