#!/usr/bin/env python3
"""Run the Open Capability Graph interoperability bakeoff.

The command writes imported candidate graphs, a merged retrieval graph, an
executed receipt, and a digest manifest.  A successful run establishes only
the checks named in the receipt; it does not authorize any imported action or
search result for execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from aidevobserver_fabric.ocg_interop import (
    run_interoperability_bakeoff,
    write_bakeoff_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC_ROOT = REPO_ROOT / "spec/open-capability-graph/v0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute the candidate-only OCG native-format interoperability bakeoff."
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=DEFAULT_SPEC_ROOT / "interoperability/fixtures",
        help="Directory containing the committed native-format fixtures.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SPEC_ROOT / "schemas/open-capability-graph.schema.json",
        help="OCG JSON Schema to validate generated documents against.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "artifacts/ocg_interop_bakeoff",
        help="Directory for graphs, receipt, and manifest.",
    )
    parser.add_argument(
        "--native-validator-path",
        type=Path,
        help="Optional Python site-packages directory containing native validators.",
    )
    parser.add_argument(
        "--wasm-tools",
        type=Path,
        help="Optional wasm-tools executable used to parse and normalize WIT.",
    )
    parser.add_argument(
        "--require-native",
        action="store_true",
        help="Fail unless every recorded native validator is available and passes.",
    )
    return parser.parse_args()


def _success(receipt: dict, require_native: bool) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for imported in receipt["imports"]:
        if not imported["schema_validation"]["valid"]:
            failures.append(f"{imported['source_format']}: generated OCG schema validation failed")
        if not imported["semantic_validation"]["valid"]:
            failures.append(f"{imported['source_format']}: generated OCG semantic validation failed")

    merged = receipt["merged_graph"]
    if not merged["schema_validation"]["valid"]:
        failures.append("merged graph: OCG schema validation failed")
    if not merged["semantic_validation"]["valid"]:
        failures.append("merged graph: OCG semantic validation failed")

    default_compatibility = receipt["compatibility_bakeoff"]["default_held_out"]
    interoperability = receipt["compatibility_bakeoff"][
        "interoperability_explicit_json_schema_projections"
    ]["metrics"]
    for name, metrics in (
        ("default compatibility", default_compatibility["metrics"]),
        ("interoperability compatibility", interoperability),
    ):
        if metrics["unsafe_safe_edges"]:
            failures.append(f"{name}: a non-safe fixture label was predicted safe")
        if metrics["exact_accuracy"] != 1.0:
            failures.append(f"{name}: checker predictions disagreed with fixture labels")

    for backend, metrics in receipt["search_bakeoff"]["aggregate"].items():
        if metrics["top1_accuracy"] != 1.0:
            failures.append(f"{backend}: top-1 result disagreed with a fixture relevance label")
        if metrics["mean_recall_at_returned_k"] != 1.0:
            failures.append(f"{backend}: failed to retrieve all fixture labels within returned k")

    if require_native and not receipt["native_validation"]["all_passed"]:
        failures.append("one or more required native validators were unavailable or failed")
    return not failures, failures


def main() -> int:
    args = parse_args()
    receipt, documents = run_interoperability_bakeoff(
        args.fixtures,
        args.schema,
        validator_path=args.native_validator_path,
        wasm_tools=args.wasm_tools,
    )
    artifact_receipt = write_bakeoff_artifacts(args.output, receipt, documents)
    passed, failures = _success(receipt, args.require_native)
    summary = {
        "passed": passed,
        "failures": failures,
        "boundary": receipt["boundary"],
        "native_validation": receipt["native_validation"],
        "merged_counts": receipt["merged_graph"]["counts"],
        "source_format_count": receipt["merged_graph"]["source_format_count"],
        "search_aggregate": receipt["search_bakeoff"]["aggregate"],
        "search_mean_backend_jaccard": receipt["search_bakeoff"]["mean_backend_jaccard"],
        "search_backend_agreement": receipt["search_bakeoff"]["backend_agreement"],
        "interoperability_compatibility_metrics": receipt["compatibility_bakeoff"][
            "interoperability_explicit_json_schema_projections"
        ]["metrics"],
        "artifact_manifest": artifact_receipt["manifest_path"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
