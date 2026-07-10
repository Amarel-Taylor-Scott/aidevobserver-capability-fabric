"""Compute a SHA-256 content digest."""

from __future__ import annotations

import hashlib
from typing import Any

PRIMITIVE_ID = "prim.crypto.sha256.v1"
LABEL = "SHA-256 hash"
DESCRIPTION = "Compute the lowercase SHA-256 digest and encoded byte length of a string."
LICENSE_SPDX = "MIT"

INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["payload"],
    "properties": {
        "payload": {"type": "string", "maxLength": 2_000_000},
        "encoding": {"type": "string", "enum": ["utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be", "ascii", "latin-1"]},
    },
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["sha256", "byte_count"],
    "properties": {
        "sha256": {"type": "string", "pattern": r"^[a-f0-9]{64}$"},
        "byte_count": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    payload = inputs.get("payload", "")
    encoding = inputs.get("encoding", "utf-8")
    if not isinstance(payload, str):
        raise TypeError(f"payload must be str, got {type(payload).__name__}")
    if not isinstance(encoding, str):
        raise TypeError(f"encoding must be str, got {type(encoding).__name__}")
    data = payload.encode(encoding)
    return {"sha256": hashlib.sha256(data).hexdigest(), "byte_count": len(data)}


PROOF_FIXTURES = (
    {
        "name": "abc_known_vector",
        "input": {"payload": "abc"},
        "expected": {"sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "byte_count": 3},
    },
    {
        "name": "unicode_utf8",
        "input": {"payload": "é"},
        "expected": {"sha256": "4a99557e4033c3539de2eb65472017cad5f9557f7a0625a09f1c3f6e2ba69c4c", "byte_count": 2},
    },
    {
        "name": "explicit_utf16_little_endian",
        "input": {"payload": "A", "encoding": "utf-16-le"},
        "expected": {"sha256": "e61c21ca716b3b1aefb7d1198f83679c4ca4d596e5792275dd6203b49216237d", "byte_count": 2},
    },
    {
        "name": "explicit_utf32_big_endian",
        "input": {"payload": "A", "encoding": "utf-32-be"},
        "expected": {"sha256": "03e3c2420f5066a5fa6e36735ed8cc4f6a251046263e1a6024f009deeee3b952", "byte_count": 4},
    },
)
