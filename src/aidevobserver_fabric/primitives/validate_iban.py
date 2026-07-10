"""Validate IBANs using country lengths and the mod-97 checksum."""

from __future__ import annotations

import re
from typing import Any

PRIMITIVE_ID = "prim.finance.validate_iban.v1"
LABEL = "Validate IBAN"
DESCRIPTION = "Normalize and validate an IBAN using its country length and ISO 13616 mod-97 checksum."
LICENSE_SPDX = "MIT"

INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["iban"],
    "properties": {"iban": {"type": "string", "minLength": 4, "maxLength": 64}},
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["iban", "valid", "reasons", "country"],
    "properties": {
        "iban": {"type": "string"},
        "valid": {"type": "boolean"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "country": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

# Source: SWIFT ISO 13616 IBAN Registry, Release 102 (June 2026), "IBAN
# length" for every listed national format. SWIFT is the ISO 13616
# Registration Authority. Keep this table synchronized with the current
# registry: https://www.swift.com/resource/iban-registry-pdf
IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16,
    "BG": 22, "BH": 22, "BI": 27, "BR": 29, "BY": 28, "CH": 21, "CR": 22,
    "CY": 28, "CZ": 24, "DE": 22, "DJ": 27, "DK": 18, "DO": 28, "EE": 20,
    "EG": 29, "ES": 24, "FI": 18, "FK": 18, "FO": 18, "FR": 27, "GB": 22,
    "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HN": 28, "HR": 21,
    "HU": 28, "IE": 22, "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30,
    "KW": 30, "KZ": 20, "LB": 28, "LC": 32, "LI": 21, "LT": 20, "LU": 20,
    "LV": 21, "LY": 25, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MN": 20,
    "MR": 27, "MT": 31, "MU": 30, "NI": 28, "NL": 18, "NO": 15, "OM": 23,
    "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22,
    "RU": 33, "SA": 24, "SC": 31, "SD": 18, "SE": 24, "SI": 19, "SK": 24,
    "SM": 27, "SO": 23, "ST": 25, "SV": 28, "TL": 23, "TN": 24, "TR": 26,
    "UA": 29, "VA": 22, "VG": 24, "XK": 20, "YE": 30,
}
IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$")


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    raw = inputs.get("iban", "")
    if not isinstance(raw, str):
        raise TypeError(f"expected iban: str, got {type(raw).__name__}")
    iban = raw.upper().replace(" ", "").replace("-", "")
    reasons: list[str] = []
    if not IBAN_RE.match(iban):
        reasons.append("format_invalid")
    else:
        country = iban[:2]
        if country not in IBAN_LENGTHS:
            reasons.append("country_unsupported")
        elif len(iban) != IBAN_LENGTHS[country]:
            reasons.append(f"length_invalid_for_{country}_expected_{IBAN_LENGTHS[country]}")
        rearranged = iban[4:] + iban[:4]
        digits = "".join(str(ord(char) - ord("A") + 10) if char.isalpha() else char for char in rearranged)
        try:
            checksum_ok = int(digits) % 97 == 1
        except ValueError:
            checksum_ok = False
        if not checksum_ok:
            reasons.append("checksum_failed")
    return {
        "iban": iban,
        "valid": not reasons,
        "reasons": reasons,
        "country": iban[:2] if len(iban) >= 2 else None,
    }


PROOF_FIXTURES = (
    {
        "name": "valid_grouped_german_iban",
        "input": {"iban": "DE89 3704 0044 0532 0130 00"},
        "expected": {"iban": "DE89370400440532013000", "valid": True, "reasons": [], "country": "DE"},
    },
    {
        "name": "bad_checksum",
        "input": {"iban": "DE89370400440532013001"},
        "expected": {"iban": "DE89370400440532013001", "valid": False, "reasons": ["checksum_failed"], "country": "DE"},
    },
    {
        "name": "valid_djibouti_iban",
        "input": {"iban": "DJ2100010000000154000100186"},
        "expected": {"iban": "DJ2100010000000154000100186", "valid": True, "reasons": [], "country": "DJ"},
    },
    {
        "name": "valid_oman_iban",
        "input": {"iban": "OM81 0180 0000 0129 9123 456"},
        "expected": {"iban": "OM810180000001299123456", "valid": True, "reasons": [], "country": "OM"},
    },
    {
        "name": "valid_seychelles_iban",
        "input": {"iban": "SC18SSCB11010000000000001497USD"},
        "expected": {"iban": "SC18SSCB11010000000000001497USD", "valid": True, "reasons": [], "country": "SC"},
    },
    {
        "name": "valid_sudan_iban",
        "input": {"iban": "SD2129010501234001"},
        "expected": {"iban": "SD2129010501234001", "valid": True, "reasons": [], "country": "SD"},
    },
)
