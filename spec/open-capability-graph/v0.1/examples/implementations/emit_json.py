"""Illustrative deterministic JSON emitter for the OCG example."""

import json


def emit_json(record: dict[str, str]) -> dict[str, str]:
    return {
        "media_type": "application/json",
        "body": json.dumps(record, sort_keys=True, separators=(",", ":")),
    }
