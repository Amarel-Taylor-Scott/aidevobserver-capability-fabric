"""Parse common date formats into ISO 8601 calendar dates."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

PRIMITIVE_ID = "prim.date.normalize.v1"
LABEL = "Normalize date"
DESCRIPTION = "Normalize a bounded set of unambiguous and day-first date formats to YYYY-MM-DD."
LICENSE_SPDX = "MIT"

INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["date"],
    "properties": {"date": {"type": "string", "maxLength": 128}},
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["input", "iso8601", "ok"],
    "properties": {
        "input": {"type": "string"},
        "iso8601": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "ok": {"type": "boolean"},
    },
    "additionalProperties": False,
}

PATTERNS = (
    ("%Y-%m-%d", re.compile(r"^[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}$")),
    ("%Y/%m/%d", re.compile(r"^[0-9]{4}/[0-9]{1,2}/[0-9]{1,2}$")),
    ("%d/%m/%Y", re.compile(r"^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}$")),
    ("%d-%m-%Y", re.compile(r"^[0-9]{1,2}-[0-9]{1,2}-[0-9]{4}$")),
    ("%Y%m%d", re.compile(r"^[0-9]{8}$")),
)

ENGLISH_MONTHS = {
    name: index
    for index, name in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"),
        start=1,
    )
}


def parse_one(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    month_first = re.fullmatch(r"([A-Za-z]+) ([0-9]{1,2}), ([0-9]{4})", value)
    day_first = re.fullmatch(r"([0-9]{1,2}) ([A-Za-z]+) ([0-9]{4})", value)
    if month_first or day_first:
        if month_first:
            month_name, day, year = month_first.groups()
        else:
            day, month_name, year = day_first.groups()  # type: ignore[union-attr]
        month = ENGLISH_MONTHS.get(month_name.casefold())
        if month is None:
            return None
        try:
            return dt.date(int(year), month, int(day)).isoformat()
        except ValueError:
            return None
    for date_format, pattern in PATTERNS:
        if pattern.match(value):
            try:
                return dt.datetime.strptime(value, date_format).date().isoformat()
            except ValueError:
                continue
    return None


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    raw = inputs.get("date", "")
    if not isinstance(raw, str):
        raise TypeError(f"date must be str, got {type(raw).__name__}")
    iso = parse_one(raw)
    return {"input": raw, "iso8601": iso, "ok": iso is not None}


PROOF_FIXTURES = (
    {"name": "month_name", "input": {"date": "July 9, 2026"}, "expected": {"input": "July 9, 2026", "iso8601": "2026-07-09", "ok": True}},
    {"name": "invalid_leap_day", "input": {"date": "2025-02-29"}, "expected": {"input": "2025-02-29", "iso8601": None, "ok": False}},
)
