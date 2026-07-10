"""Profile CSV columns using only the Python standard library."""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from typing import Any

PRIMITIVE_ID = "candidate.csv.profile_columns.v0"
LABEL = "Profile CSV columns"
DESCRIPTION = "Parse CSV text and report deterministic counts, examples, and conservative scalar type inference for each column."
LICENSE_SPDX = "MIT"
MAX_COLUMNS = 4096
MAX_PROFILE_CELLS = 5_000_000

# Match the declared maximum input size rather than Python's smaller default
# CSV field limit (131,072 characters).
csv.field_size_limit(2_000_000)

INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["csv_text"],
    "properties": {
        "csv_text": {"type": "string", "maxLength": 2_000_000},
        "delimiter": {"type": "string", "minLength": 1, "maxLength": 1},
        "has_header": {"type": "boolean"},
        "sample_size": {"type": "integer", "minimum": 1, "maximum": 100_000},
        "null_values": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
    },
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["delimiter", "row_count", "sampled_row_count", "column_count", "columns"],
    "properties": {
        "delimiter": {"type": "string", "minLength": 1, "maxLength": 1},
        "row_count": {"type": "integer", "minimum": 0},
        "sampled_row_count": {"type": "integer", "minimum": 0},
        "column_count": {"type": "integer", "minimum": 0, "maximum": MAX_COLUMNS},
        "columns": {
            "type": "array",
            "maxItems": MAX_COLUMNS,
            "items": {
                "type": "object",
                "required": ["name", "index", "non_null_count", "null_count", "unique_count", "inferred_type", "examples"],
                "properties": {
                    "name": {"type": "string"},
                    "index": {"type": "integer", "minimum": 0},
                    "non_null_count": {"type": "integer", "minimum": 0},
                    "null_count": {"type": "integer", "minimum": 0},
                    "unique_count": {"type": "integer", "minimum": 0},
                    "inferred_type": {"type": "string", "enum": ["null", "boolean", "integer", "number", "date", "string"]},
                    "examples": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}

INTEGER_RE = re.compile(r"^[+-]?\d+$")
NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
TRUE_VALUES = {"true", "yes", "y", "1"}
FALSE_VALUES = {"false", "no", "n", "0"}


def _delimiter(csv_text: str, explicit: str | None) -> str:
    if explicit is not None:
        return explicit
    sample = csv_text[:8192]
    if not sample:
        return ","
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        return ","


def _column_names(raw_names: list[str], width: int) -> list[str]:
    names: list[str] = []
    counts: dict[str, int] = {}
    for index in range(width):
        base = raw_names[index].strip() if index < len(raw_names) else ""
        base = base or f"column_{index + 1}"
        counts[base] = counts.get(base, 0) + 1
        names.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return names


def _is_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _inferred_type(values: list[str]) -> str:
    if not values:
        return "null"
    lowered = [value.lower() for value in values]
    if all(value in TRUE_VALUES | FALSE_VALUES for value in lowered):
        return "boolean"
    if all(INTEGER_RE.fullmatch(value) for value in values):
        return "integer"
    if all(NUMBER_RE.fullmatch(value) for value in values):
        return "number"
    if all(_is_date(value) for value in values):
        return "date"
    return "string"


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    csv_text = inputs.get("csv_text", "")
    explicit_delimiter = inputs.get("delimiter")
    has_header = inputs.get("has_header", True)
    sample_size = inputs.get("sample_size", 10_000)
    raw_null_values = inputs.get("null_values", ["", "null", "none", "na", "n/a"])
    if not isinstance(csv_text, str):
        raise TypeError("csv_text must be str")
    delimiter = _delimiter(csv_text, explicit_delimiter)
    reader = iter(csv.reader(io.StringIO(csv_text), delimiter=delimiter))
    try:
        first_row = next(reader)
    except StopIteration:
        return {"delimiter": delimiter, "row_count": 0, "sampled_row_count": 0, "column_count": 0, "columns": []}
    raw_names = first_row if has_header else []
    width = len(raw_names)
    if width > MAX_COLUMNS:
        raise ValueError(f"CSV has {width} columns; maximum is {MAX_COLUMNS}")
    row_count = 0
    sampled_rows: list[list[str]] = []

    def observe(row: list[str]) -> None:
        nonlocal row_count, width
        row_count += 1
        width = max(width, len(row))
        if width > MAX_COLUMNS:
            raise ValueError(f"CSV has {width} columns; maximum is {MAX_COLUMNS}")
        if len(sampled_rows) < sample_size:
            sampled_rows.append(row)

    if not has_header:
        observe(first_row)
    for row in reader:
        observe(row)
    if width * len(sampled_rows) > MAX_PROFILE_CELLS:
        raise ValueError(
            f"CSV profile requires {width * len(sampled_rows)} sampled cells; maximum is {MAX_PROFILE_CELLS}"
        )
    names = _column_names(raw_names, width)
    null_values = {value.strip().lower() for value in raw_null_values}
    columns: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        present: list[str] = []
        null_count = 0
        for row in sampled_rows:
            value = row[index].strip() if index < len(row) else ""
            if value.lower() in null_values:
                null_count += 1
            else:
                present.append(value)
        examples = list(dict.fromkeys(present))[:3]
        columns.append(
            {
                "name": name,
                "index": index,
                "non_null_count": len(present),
                "null_count": null_count,
                "unique_count": len(set(present)),
                "inferred_type": _inferred_type(present),
                "examples": examples,
            }
        )
    return {
        "delimiter": delimiter,
        "row_count": row_count,
        "sampled_row_count": len(sampled_rows),
        "column_count": width,
        "columns": columns,
    }


PROOF_FIXTURES = (
    {
        "name": "typed_columns_and_nulls",
        "input": {"csv_text": "name,age,active,joined\nAlice,30,true,2026-01-02\nBob,,false,2025-12-31\nAlice,41,true,2024-06-15\n"},
        "expected": {
            "delimiter": ",",
            "row_count": 3,
            "sampled_row_count": 3,
            "column_count": 4,
            "columns": [
                {"name": "name", "index": 0, "non_null_count": 3, "null_count": 0, "unique_count": 2, "inferred_type": "string", "examples": ["Alice", "Bob"]},
                {"name": "age", "index": 1, "non_null_count": 2, "null_count": 1, "unique_count": 2, "inferred_type": "integer", "examples": ["30", "41"]},
                {"name": "active", "index": 2, "non_null_count": 3, "null_count": 0, "unique_count": 2, "inferred_type": "boolean", "examples": ["true", "false"]},
                {"name": "joined", "index": 3, "non_null_count": 3, "null_count": 0, "unique_count": 3, "inferred_type": "date", "examples": ["2026-01-02", "2025-12-31", "2024-06-15"]},
            ],
        },
    },
    {
        "name": "headerless_semicolon_and_sample",
        "input": {"csv_text": "1;2.5\n2;3.5\n3;4.5\n", "delimiter": ";", "has_header": False, "sample_size": 2},
        "expected": {
            "delimiter": ";",
            "row_count": 3,
            "sampled_row_count": 2,
            "column_count": 2,
            "columns": [
                {"name": "column_1", "index": 0, "non_null_count": 2, "null_count": 0, "unique_count": 2, "inferred_type": "integer", "examples": ["1", "2"]},
                {"name": "column_2", "index": 1, "non_null_count": 2, "null_count": 0, "unique_count": 2, "inferred_type": "number", "examples": ["2.5", "3.5"]},
            ],
        },
    },
)
