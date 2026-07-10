"""Extract HTTP and HTTPS URLs from text."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

PRIMITIVE_ID = "prim.text.extract_url.v1"
LABEL = "Extract URLs"
DESCRIPTION = "Extract unique HTTP(S) URLs and trim common trailing prose punctuation."
LICENSE_SPDX = "MIT"

INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["text"],
    "properties": {"text": {"type": "string", "maxLength": 1_000_000}},
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["urls", "count"],
    "properties": {
        "urls": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "count": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}

URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)


def clean_url(value: str) -> str | None:
    value = value.rstrip(",.;:!?>'\"")
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        while value.endswith(closing) and value.count(closing) > value.count(opening):
            value = value[:-1]
    parsed = urlsplit(value)
    host = parsed.hostname
    if parsed.scheme.casefold() not in {"http", "https"} or not host:
        return None
    if host.startswith(".") or host.endswith(".") or ".." in host:
        return None
    if ":" not in host and re.fullmatch(r"[A-Za-z0-9.-]+", host) is None:
        return None
    return value


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    text = inputs.get("text", "")
    if not isinstance(text, str):
        raise TypeError(f"expected text: str, got {type(text).__name__}")
    seen: set[str] = set()
    urls: list[str] = []
    for candidate in URL_RE.findall(text):
        url = clean_url(candidate)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return {"urls": urls, "count": len(urls)}


PROOF_FIXTURES = (
    {
        "name": "trim_and_deduplicate",
        "input": {"text": "See https://example.com/a?q=1, then http://test.dev/x). See https://example.com/a?q=1."},
        "expected": {"urls": ["https://example.com/a?q=1", "http://test.dev/x"], "count": 2},
    },
    {"name": "empty", "input": {"text": ""}, "expected": {"urls": [], "count": 0}},
)
