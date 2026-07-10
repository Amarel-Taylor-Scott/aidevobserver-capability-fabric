"""Approximate token count using a character heuristic."""

from __future__ import annotations

from typing import Any

PRIMITIVE_ID = "prim.text.count_tokens_approx.v1"
LABEL = "Approximate token count"
DESCRIPTION = "Estimate non-CJK tokens at four characters each, rounded up, and CJK characters at one token each."
LICENSE_SPDX = "MIT"

INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["text"],
    "properties": {"text": {"type": "string", "maxLength": 2_000_000}},
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["char_count", "cjk_char_count", "approx_tokens", "method"],
    "properties": {
        "char_count": {"type": "integer", "minimum": 0},
        "cjk_char_count": {"type": "integer", "minimum": 0},
        "approx_tokens": {"type": "integer", "minimum": 0},
        "method": {"type": "string"},
    },
    "additionalProperties": False,
}


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    text = inputs.get("text", "")
    if not isinstance(text, str):
        raise TypeError(f"text must be str, got {type(text).__name__}")
    char_count = len(text)
    cjk = sum(1 for char in text if "一" <= char <= "鿿" or "぀" <= char <= "ヿ" or "가" <= char <= "힯")
    non_cjk = char_count - cjk
    approx = cjk + (non_cjk + 3) // 4
    return {
        "char_count": char_count,
        "cjk_char_count": cjk,
        "approx_tokens": approx,
        "method": "ceil(non-cjk-chars/4) + 1-per-cjk-char",
    }


PROOF_FIXTURES = (
    {
        "name": "ascii",
        "input": {"text": "abcdefghijkl"},
        "expected": {"char_count": 12, "cjk_char_count": 0, "approx_tokens": 3, "method": "ceil(non-cjk-chars/4) + 1-per-cjk-char"},
    },
    {
        "name": "mixed_cjk",
        "input": {"text": "hello世界"},
        "expected": {"char_count": 7, "cjk_char_count": 2, "approx_tokens": 4, "method": "ceil(non-cjk-chars/4) + 1-per-cjk-char"},
    },
    {
        "name": "single_ascii_character",
        "input": {"text": "a"},
        "expected": {"char_count": 1, "cjk_char_count": 0, "approx_tokens": 1, "method": "ceil(non-cjk-chars/4) + 1-per-cjk-char"},
    },
)
