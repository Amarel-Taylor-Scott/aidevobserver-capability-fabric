"""Candidate-only social source ingestion through configurable RapidAPI APIs."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib import parse, request


DEFAULT_KEY_ENV = "RAPIDAPI_KEY"


@dataclass(frozen=True, slots=True)
class SocialSource:
    source_id: str
    label: str
    url: str
    platform: str = "facebook"
    cadence: str = "daily"
    candidate_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RapidApiProviderSpec:
    provider_id: str
    name: str
    host: str
    path: str
    method: str = "GET"
    base_url: str | None = None
    url_param: str = "url"
    limit_param: str | None = "limit"
    records_path: str | None = None
    static_query: dict[str, str] = field(default_factory=dict)
    docs_url: str | None = None
    key_env: str = DEFAULT_KEY_ENV
    candidate_only: bool = True

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "RapidApiProviderSpec":
        return RapidApiProviderSpec(
            provider_id=str(data["provider_id"]),
            name=str(data["name"]),
            host=str(data["host"]),
            path=str(data["path"]),
            method=str(data.get("method", "GET")).upper(),
            base_url=data.get("base_url"),
            url_param=str(data.get("url_param", "url")),
            limit_param=data.get("limit_param", "limit"),
            records_path=data.get("records_path"),
            static_query={str(k): str(v) for k, v in data.get("static_query", {}).items()},
            docs_url=data.get("docs_url"),
            key_env=str(data.get("key_env", DEFAULT_KEY_ENV)),
            candidate_only=bool(data.get("candidate_only", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RequestPlan:
    provider_id: str
    source_id: str
    method: str
    url: str
    headers: dict[str, str]
    key_env: str
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NormalizedSocialPost:
    source_id: str
    source_url: str
    platform: str
    post_id: str | None
    post_url: str | None
    author: str | None
    text: str | None
    created_at: str | None
    metrics: dict[str, Any]
    raw_digest: str
    candidate_only: bool = True
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_FACEBOOK_SOURCES: tuple[SocialSource, ...] = (
    SocialSource("facebook.deeprepo", "DeepRepo", "https://www.facebook.com/DeepRepo"),
    SocialSource("facebook.aidev_repo", "AI Dev Repo", "https://www.facebook.com/aidev.repo"),
    SocialSource("facebook.ai_reporter_kh", "AI Reporter KH", "https://www.facebook.com/AIReporterKH"),
    SocialSource(
        "facebook.profile_61590784647199",
        "Facebook profile 61590784647199",
        "https://www.facebook.com/profile.php?id=61590784647199",
    ),
    SocialSource(
        "facebook.profile_61573369875592",
        "Facebook profile 61573369875592",
        "https://www.facebook.com/profile.php?id=61573369875592",
    ),
)


def load_social_sources(path: Path | None = None) -> tuple[SocialSource, ...]:
    if path is None:
        return DEFAULT_FACEBOOK_SOURCES
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("sources", data) if isinstance(data, dict) else data
    return tuple(
        SocialSource(
            source_id=str(row["source_id"]),
            label=str(row["label"]),
            url=str(row["url"]),
            platform=str(row.get("platform", "facebook")),
            cadence=str(row.get("cadence", "daily")),
            candidate_only=bool(row.get("candidate_only", True)),
        )
        for row in rows
    )


def load_provider_spec(path: Path) -> RapidApiProviderSpec:
    return RapidApiProviderSpec.from_dict(json.loads(path.read_text(encoding="utf-8")))


def compact_sources(sources: Iterable[SocialSource]) -> str:
    lines = [
        "AIDevObserver social sources",
        "BOUNDARY candidate_intake=true serves_truth=false",
    ]
    for source in sources:
        lines.append(
            f"SOC {source.source_id} platform:{source.platform} cadence:{source.cadence} "
            f"label:{source.label} url:{source.url}"
        )
    return "\n".join(lines) + "\n"


def sources_json(sources: Iterable[SocialSource]) -> str:
    source_tuple = tuple(sources)
    return json.dumps(
        {
            "catalog_id": "aidevobserver.social_sources.v0",
            "serves_truth": False,
            "record_count": len(source_tuple),
            "sources": [source.to_dict() for source in source_tuple],
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def build_request_plan(
    provider: RapidApiProviderSpec,
    source: SocialSource,
    *,
    limit: int | None = None,
    key_value: str | None = None,
    redact_key: bool = True,
) -> RequestPlan:
    base_url = provider.base_url or f"https://{provider.host}"
    path = provider.path if provider.path.startswith("/") else f"/{provider.path}"
    query = dict(provider.static_query)
    query[provider.url_param] = source.url
    if limit is not None and provider.limit_param:
        query[provider.limit_param] = str(limit)
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url = f"{url}?{parse.urlencode(query)}"
    key_header = "<redacted>" if redact_key else (key_value or "")
    headers = {
        "Accept": "application/json",
        "X-RapidAPI-Host": provider.host,
        "X-RapidAPI-Key": key_header,
    }
    return RequestPlan(
        provider_id=provider.provider_id,
        source_id=source.source_id,
        method=provider.method,
        url=url,
        headers=headers,
        key_env=provider.key_env,
    )


def request_plans(
    provider: RapidApiProviderSpec,
    sources: Iterable[SocialSource],
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    return [build_request_plan(provider, source, limit=limit).to_dict() for source in sources]


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _get_path(value: Any, dotted_path: str | None) -> Any:
    if not dotted_path:
        return value
    current = value
    for part in dotted_path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


def _first_present(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _coerce_items(payload: Any, records_path: str | None = None) -> list[Any]:
    selected = _get_path(payload, records_path)
    if isinstance(selected, list):
        return selected
    if isinstance(selected, dict):
        for path in (
            "posts",
            "data",
            "results",
            "items",
            "response.posts",
            "response.data",
            "result.posts",
            "result.data",
        ):
            maybe_items = _get_path(selected, path)
            if isinstance(maybe_items, list):
                return maybe_items
        lists = [value for value in selected.values() if isinstance(value, list)]
        if lists:
            return lists[0]
    return []


def normalize_posts(
    payload: Any,
    source: SocialSource,
    *,
    records_path: str | None = None,
) -> tuple[NormalizedSocialPost, ...]:
    posts: list[NormalizedSocialPost] = []
    for item in _coerce_items(payload, records_path):
        if not isinstance(item, dict):
            continue
        post_id = _first_present(item, ("post_id", "id", "postId", "postID", "fbid"))
        post_url = _first_present(item, ("url", "post_url", "permalink_url", "permalink", "link"))
        author = _first_present(item, ("author", "owner", "page_name", "from_name", "username", "name"))
        text = _first_present(item, ("text", "message", "content", "caption", "description", "body"))
        created_at = _first_present(item, ("created_at", "created_time", "timestamp", "time", "date"))
        metrics = {
            key: item[key]
            for key in (
                "likes",
                "like_count",
                "comments",
                "comment_count",
                "shares",
                "share_count",
                "reactions",
                "reaction_count",
            )
            if key in item
        }
        posts.append(
            NormalizedSocialPost(
                source_id=source.source_id,
                source_url=source.url,
                platform=source.platform,
                post_id=str(post_id) if post_id is not None else None,
                post_url=str(post_url) if post_url is not None else None,
                author=str(author) if author is not None else None,
                text=str(text) if text is not None else None,
                created_at=str(created_at) if created_at is not None else None,
                metrics=metrics,
                raw_digest=_digest(item),
            )
        )
    return tuple(posts)


def fetch_source(
    provider: RapidApiProviderSpec,
    source: SocialSource,
    *,
    limit: int | None = None,
    key_env: str | None = None,
    timeout: float = 30.0,
) -> tuple[NormalizedSocialPost, ...]:
    env_name = key_env or provider.key_env
    key_value = os.environ.get(env_name)
    if not key_value:
        raise RuntimeError(f"missing RapidAPI key environment variable: {env_name}")
    plan = build_request_plan(provider, source, limit=limit, key_value=key_value, redact_key=False)
    req = request.Request(
        plan.url,
        headers={
            **plan.headers,
            "User-Agent": "aidevobserver-capability-fabric/0.1",
        },
        method=plan.method,
    )
    with request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return normalize_posts(payload, source, records_path=provider.records_path)


def scrape_sources(
    provider: RapidApiProviderSpec,
    sources: Iterable[SocialSource],
    *,
    limit: int | None = None,
    key_env: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for source in sources:
        records.extend(
            post.to_dict()
            for post in fetch_source(provider, source, limit=limit, key_env=key_env, timeout=timeout)
        )
    return {
        "provider": provider.to_dict(),
        "record_count": len(records),
        "records": records,
        "serves_truth": False,
        "candidate_only": True,
    }

