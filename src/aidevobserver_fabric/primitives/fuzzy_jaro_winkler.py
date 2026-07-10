"""Compute Jaro-Winkler string similarity."""

from __future__ import annotations

from typing import Any

PRIMITIVE_ID = "prim.similarity.jaro_winkler.v1"
LABEL = "Jaro-Winkler similarity"
DESCRIPTION = "Compute deterministic Jaro-Winkler similarity for entity matching and deduplication."
LICENSE_SPDX = "MIT"

INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["a", "b"],
    "properties": {
        "a": {"type": "string", "maxLength": 2048},
        "b": {"type": "string", "maxLength": 2048},
        "case_insensitive": {"type": "boolean"},
    },
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["a", "b", "case_insensitive", "score"],
    "properties": {
        "a": {"type": "string", "maxLength": 2048},
        "b": {"type": "string", "maxLength": 2048},
        "case_insensitive": {"type": "boolean"},
        "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "additionalProperties": False,
}


def jaro(first: str, second: str) -> float:
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    first_len, second_len = len(first), len(second)
    match_distance = max(0, max(first_len, second_len) // 2 - 1)
    first_matches = [False] * first_len
    second_matches = [False] * second_len
    matches = 0
    for index, first_char in enumerate(first):
        start = max(0, index - match_distance)
        end = min(index + match_distance + 1, second_len)
        for second_index in range(start, end):
            if second_matches[second_index] or first_char != second[second_index]:
                continue
            first_matches[index] = True
            second_matches[second_index] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    transpositions = 0
    second_index = 0
    for index in range(first_len):
        if not first_matches[index]:
            continue
        while not second_matches[second_index]:
            second_index += 1
        if first[index] != second[second_index]:
            transpositions += 1
        second_index += 1
    return (
        matches / first_len
        + matches / second_len
        + (matches - transpositions / 2) / matches
    ) / 3.0


def jaro_winkler(first: str, second: str, scale: float = 0.1, prefix_max: int = 4) -> float:
    score = jaro(first, second)
    if score == 0:
        return 0.0
    prefix = 0
    for first_char, second_char in zip(first[:prefix_max], second[:prefix_max]):
        if first_char != second_char:
            break
        prefix += 1
    return score + prefix * scale * (1 - score)


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    first = inputs.get("a", "")
    second = inputs.get("b", "")
    if not isinstance(first, str) or not isinstance(second, str):
        raise TypeError("a and b must be strings")
    case_insensitive = bool(inputs.get("case_insensitive", True))
    first_cmp = first.lower() if case_insensitive else first
    second_cmp = second.lower() if case_insensitive else second
    return {
        "a": first,
        "b": second,
        "case_insensitive": case_insensitive,
        "score": round(jaro_winkler(first_cmp, second_cmp), 6),
    }


PROOF_FIXTURES = (
    {
        "name": "canonical_example",
        "input": {"a": "MARTHA", "b": "MARHTA", "case_insensitive": False},
        "expected": {"a": "MARTHA", "b": "MARHTA", "case_insensitive": False, "score": 0.961111},
    },
    {
        "name": "single_character_identity",
        "input": {"a": "A", "b": "a"},
        "expected": {"a": "A", "b": "a", "case_insensitive": True, "score": 1.0},
    },
)
