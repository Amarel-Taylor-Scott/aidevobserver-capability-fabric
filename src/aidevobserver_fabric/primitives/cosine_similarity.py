"""Compute cosine similarity between two equal-length vectors."""

from __future__ import annotations

import math
from typing import Any

PRIMITIVE_ID = "prim.similarity.cosine.v1"
LABEL = "Cosine similarity"
DESCRIPTION = "Compute cosine similarity for two equal-length numeric vectors without third-party dependencies."
LICENSE_SPDX = "MIT"

INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["a", "b"],
    "properties": {
        "a": {"type": "array", "maxItems": 100_000, "items": {"type": "number", "minimum": -1e308, "maximum": 1e308}},
        "b": {"type": "array", "maxItems": 100_000, "items": {"type": "number", "minimum": -1e308, "maximum": 1e308}},
    },
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["score", "dim"],
    "properties": {
        "score": {"type": "number", "minimum": -1.0, "maximum": 1.0},
        "dim": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    first = inputs.get("a", [])
    second = inputs.get("b", [])
    if not isinstance(first, list) or not isinstance(second, list):
        raise TypeError("a and b must be lists of numbers")
    if len(first) != len(second):
        raise ValueError(f"length mismatch: {len(first)} vs {len(second)}")
    if not first:
        return {"score": 0.0, "dim": 0}
    first_values = [float(value) for value in first]
    second_values = [float(value) for value in second]
    first_scale = max(abs(value) for value in first_values)
    second_scale = max(abs(value) for value in second_values)
    if first_scale == 0.0 or second_scale == 0.0:
        return {"score": 0.0, "dim": len(first)}
    first_scaled = [value / first_scale for value in first_values]
    second_scaled = [value / second_scale for value in second_values]
    dot = math.fsum(left * right for left, right in zip(first_scaled, second_scaled))
    first_norm = math.sqrt(math.fsum(value * value for value in first_scaled))
    second_norm = math.sqrt(math.fsum(value * value for value in second_scaled))
    score = dot / (first_norm * second_norm)
    if not math.isfinite(score):
        raise ValueError("cosine score is not finite")
    # Guard against a one-ulp excursion beyond the schema boundary.
    score = max(-1.0, min(1.0, score))
    return {"score": score, "dim": len(first)}


PROOF_FIXTURES = (
    {"name": "orthogonal", "input": {"a": [1, 0], "b": [0, 1]}, "expected": {"score": 0.0, "dim": 2}},
    {"name": "identical", "input": {"a": [1, 2, 3], "b": [1, 2, 3]}, "expected": {"score": 1.0, "dim": 3}},
    {"name": "empty", "input": {"a": [], "b": []}, "expected": {"score": 0.0, "dim": 0}},
)
