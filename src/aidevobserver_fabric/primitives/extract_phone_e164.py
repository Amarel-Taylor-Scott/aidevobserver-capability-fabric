"""Extract and heuristically normalize common phone forms to E.164."""

from __future__ import annotations

import re
from typing import Any

PRIMITIVE_ID = "prim.text.extract_phone_e164.v1"
LABEL = "Extract E.164 phone numbers"
DESCRIPTION = "Extract common phone-number forms and normalize them to E.164 with a caller-supplied default country code."
LICENSE_SPDX = "MIT"

INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["text"],
    "properties": {
        "text": {"type": "string", "maxLength": 1_000_000},
        "default_country_code": {"type": "string", "pattern": r"^\+[1-9][0-9]{0,3}$"},
    },
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["phones_e164", "count"],
    "properties": {
        "phones_e164": {
            "type": "array",
            "items": {"type": "string", "pattern": r"^\+[1-9][0-9]{7,14}$"},
            "uniqueItems": True,
        },
        "count": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}

PHONE_CANDIDATE = re.compile(r"(?:(?:\+|00)\s*)?(?:\(?[0-9]{1,4}\)?[\s\-.]?){2,6}[0-9]{2,9}")
DIGITS = re.compile(r"[0-9]")
KEEP = re.compile(r"[^0-9+]")
E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


def normalize(raw: str, default_cc: str = "+1") -> str:
    value = KEEP.sub("", raw)
    if value.startswith("00"):
        value = "+" + value[2:]
    if not value.startswith("+"):
        if len(value) == 10:
            value = default_cc + value
        elif len(value) > 10:
            value = "+" + value
    return value


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    text = inputs.get("text", "")
    default_cc = inputs.get("default_country_code", "+1")
    if not isinstance(text, str):
        raise TypeError(f"text must be str, got {type(text).__name__}")
    if not isinstance(default_cc, str):
        raise TypeError("default_country_code must be str")
    seen: set[str] = set()
    output: list[str] = []
    for candidate in PHONE_CANDIDATE.findall(text):
        digit_count = len(DIGITS.findall(candidate))
        if not 7 <= digit_count <= 15:
            continue
        value = normalize(candidate, default_cc)
        if E164.fullmatch(value) and value not in seen:
            seen.add(value)
            output.append(value)
    return {"phones_e164": output, "count": len(output)}


PROOF_FIXTURES = (
    {
        "name": "us_and_international",
        "input": {"text": "Call (212) 555-0100 or +44 20 7946 0958."},
        "expected": {"phones_e164": ["+12125550100", "+442079460958"], "count": 2},
    },
    {
        "name": "custom_country_code",
        "input": {"text": "917 555 0123", "default_country_code": "+63"},
        "expected": {"phones_e164": ["+639175550123"], "count": 1},
    },
)
