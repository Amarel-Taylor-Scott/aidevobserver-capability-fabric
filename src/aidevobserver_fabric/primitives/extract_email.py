"""Extract RFC-5322-lite email addresses from text."""

from __future__ import annotations

import re
from typing import Any

PRIMITIVE_ID = "prim.text.extract_email.v1"
LABEL = "Extract email addresses"
DESCRIPTION = "Extract unique RFC-5322-lite email addresses while preserving first-seen order."
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
    "required": ["emails", "count"],
    "properties": {
        "emails": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "count": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    text = inputs.get("text", "")
    if not isinstance(text, str):
        raise TypeError(f"expected text: str, got {type(text).__name__}")
    seen: set[str] = set()
    emails: list[str] = []
    for email in EMAIL_RE.findall(text):
        key = email.lower()
        if key not in seen:
            seen.add(key)
            emails.append(email)
    return {"emails": emails, "count": len(emails)}


PROOF_FIXTURES = (
    {
        "name": "extract_and_casefold_deduplicate",
        "input": {"text": "Email Alice@example.com, bob@test.org, and ALICE@example.com."},
        "expected": {"emails": ["Alice@example.com", "bob@test.org"], "count": 2},
    },
    {"name": "no_matches", "input": {"text": "No address here."}, "expected": {"emails": [], "count": 0}},
)
