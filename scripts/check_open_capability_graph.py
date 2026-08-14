#!/usr/bin/env python3
"""Validate Open Capability Graph documents and print a conformance receipt."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aidevobserver_fabric.ocg_conformance import validate_file  # noqa: E402


DEFAULT_DOCUMENT = REPO_ROOT / "spec/open-capability-graph/v0.1/examples/customer-record-pipeline.ocg.json"
DEFAULT_SCHEMA = REPO_ROOT / "spec/open-capability-graph/v0.1/schemas/open-capability-graph.schema.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("documents", nargs="*", type=Path, default=[DEFAULT_DOCUMENT])
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--as-of", help="ISO-8601 time for current-evidence and relation-validity checks")
    parser.add_argument(
        "--structural-only",
        action="store_true",
        help="return success for structurally conformant historical records even when they are not currently eligible",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
    receipts = []
    valid = True
    for document in args.documents:
        path = document if document.is_absolute() else (Path.cwd() / document)
        result = validate_file(path, schema_path=args.schema, as_of=as_of)
        receipt = {"document": str(path.resolve()), **result.to_dict()}
        receipts.append(receipt)
        valid = valid and (result.valid if args.structural_only else result.currently_eligible)
    output: object = receipts[0] if len(receipts) == 1 else receipts
    if args.as_json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        for receipt in receipts:
            state = "CONFORMANT" if receipt["valid"] else "INVALID"
            if not receipt["eligibility_evaluated"]:
                eligibility = "ELIGIBILITY_NOT_EVALUATED"
            else:
                eligibility = (
                    "CURRENTLY_ELIGIBLE"
                    if receipt["currently_eligible"]
                    else "NOT_CURRENTLY_ELIGIBLE"
                )
            counts = ", ".join(f"{key}={value}" for key, value in sorted(receipt["counts"].items()))
            print(f"{state} {eligibility} {receipt['document']}")
            print(
                f"  schema_validation={receipt['schema_validation']} "
                f"profiles={','.join(receipt['validated_profiles']) or 'none'} "
                f"evaluated_at={receipt['evaluated_at']} {counts}"
            )
            for warning in receipt["warnings"]:
                print(f"  warning: {warning}")
            for error in receipt["errors"]:
                print(f"  error: {error}")
            for error in receipt["eligibility_errors"]:
                print(f"  eligibility_error: {error}")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
