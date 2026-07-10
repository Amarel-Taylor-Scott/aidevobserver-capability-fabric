"""Validate digit strings with the Luhn mod-10 checksum."""

from __future__ import annotations

from typing import Any

PRIMITIVE_ID = "prim.validation.luhn.v1"
LABEL = "Validate Luhn checksum"
DESCRIPTION = "Strip spaces and hyphens and validate a digit string with the Luhn mod-10 algorithm."
LICENSE_SPDX = "MIT"

INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["value"],
    "properties": {"value": {"type": "string", "maxLength": 10_000}},
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["value", "digits", "valid", "digit_count"],
    "properties": {
        "value": {"type": "string"},
        "digits": {"type": "string"},
        "valid": {"type": "boolean"},
        "digit_count": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}


def luhn_check(digits: str) -> bool:
    total = 0
    flip = False
    for character in reversed(digits):
        if character < "0" or character > "9":
            return False
        number = int(character)
        if flip:
            number *= 2
            if number > 9:
                number -= 9
        total += number
        flip = not flip
    return total % 10 == 0


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    raw = inputs.get("value", "")
    if not isinstance(raw, str):
        raise TypeError(f"expected value: str, got {type(raw).__name__}")
    digits = raw.replace(" ", "").replace("-", "")
    valid = bool(digits) and digits.isascii() and digits.isdigit() and luhn_check(digits)
    return {"value": raw, "digits": digits, "valid": valid, "digit_count": len(digits)}


PROOF_FIXTURES = (
    {
        "name": "valid_grouped_value",
        "input": {"value": "4539 1488 0343 6467"},
        "expected": {"value": "4539 1488 0343 6467", "digits": "4539148803436467", "valid": True, "digit_count": 16},
    },
    {
        "name": "invalid_value",
        "input": {"value": "4539148803436468"},
        "expected": {"value": "4539148803436468", "digits": "4539148803436468", "valid": False, "digit_count": 16},
    },
)
