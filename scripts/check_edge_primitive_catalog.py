#!/usr/bin/env python3
"""Validate the generated edge primitive catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_PACK = Path("generated/edge_primitive_catalog")


REQUIRED_FILES = (
    "manifest.json",
    "primitive_families.jsonl",
    "runtime_wrappers.jsonl",
    "resolved_primitives.jsonl",
    "compatibility_edges.jsonl",
    "route_templates.jsonl",
    "candidate_bundle_examples.jsonl",
    "README.md",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AssertionError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return rows


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_candidate(row: dict[str, Any], row_id: str) -> None:
    require(row.get("candidate") is True, f"{row_id}: candidate must be true")
    require(row.get("serves_truth") is False, f"{row_id}: serves_truth must be false")


def require_text(row: dict[str, Any], row_id: str, *fields: str) -> None:
    for field in fields:
        require(isinstance(row.get(field), str) and row[field].strip(), f"{row_id}: missing {field}")


def check_manifest(pack: Path) -> dict[str, Any]:
    for filename in REQUIRED_FILES:
        require(pack.joinpath(filename).exists(), f"missing {filename}")
    manifest = json.loads(pack.joinpath("manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("candidate") is True, "manifest candidate must be true")
    require(manifest.get("serves_truth") is False, "manifest serves_truth must be false")
    files = manifest.get("files")
    require(isinstance(files, dict), "manifest files must be an object")
    for filename, meta in files.items():
        path = pack / filename
        require(path.exists(), f"manifest references missing file {filename}")
        rows = read_jsonl(path)
        require(meta.get("rows") == len(rows), f"{filename}: row count mismatch")
        require(meta.get("sha256") == sha256_file(path), f"{filename}: sha256 mismatch")
    return manifest


def check_pack(pack: Path) -> dict[str, int]:
    check_manifest(pack)
    families = read_jsonl(pack / "primitive_families.jsonl")
    wrappers = read_jsonl(pack / "runtime_wrappers.jsonl")
    resolved = read_jsonl(pack / "resolved_primitives.jsonl")
    edges = read_jsonl(pack / "compatibility_edges.jsonl")
    routes = read_jsonl(pack / "route_templates.jsonl")
    bundles = read_jsonl(pack / "candidate_bundle_examples.jsonl")

    require(len(families) >= 3500, "expected at least 3500 primitive families")
    require(len(wrappers) >= 10, "expected at least 10 runtime wrappers")
    require(len(resolved) >= 15000, "expected at least 15000 resolved primitives")
    require(len(edges) >= 50000, "expected at least 50000 compatibility edges")
    require(len(routes) >= 1000, "expected at least 1000 route templates")
    require(len(bundles) >= 500, "expected at least 500 candidate bundle examples")

    family_by_id: dict[str, dict[str, Any]] = {}
    for row in families:
        row_id = row.get("family_id", "<missing-family-id>")
        require_text(row, row_id, "family_id", "record_type", "input_edge", "output_edge", "source_ref_policy")
        require(row["record_type"] == "primitive_family", f"{row_id}: wrong record_type")
        require_candidate(row, row_id)
        require(isinstance(row.get("problem_solution"), dict), f"{row_id}: missing problem_solution")
        for key in ("problem", "naive_agent_failure", "solution"):
            require_text(row["problem_solution"], row_id, key)
        require(row.get("proof_requirements"), f"{row_id}: missing proof_requirements")
        require(row.get("effects") is not None, f"{row_id}: missing effects")
        require(row_id not in family_by_id, f"duplicate family_id {row_id}")
        family_by_id[row_id] = row

    wrapper_by_id: dict[str, dict[str, Any]] = {}
    for row in wrappers:
        row_id = row.get("wrapper_id", "<missing-wrapper-id>")
        require_text(row, row_id, "wrapper_id", "record_type", "title", "runtime_target")
        require(row["record_type"] == "runtime_wrapper", f"{row_id}: wrong record_type")
        require_candidate(row, row_id)
        require(row_id not in wrapper_by_id, f"duplicate wrapper_id {row_id}")
        wrapper_by_id[row_id] = row

    resolved_by_id: dict[str, dict[str, Any]] = {}
    for row in resolved:
        row_id = row.get("primitive_id", "<missing-primitive-id>")
        require_text(row, row_id, "primitive_id", "record_type", "family_id", "wrapper_id", "input_edge", "output_edge")
        require(row["record_type"] == "resolved_primitive", f"{row_id}: wrong record_type")
        require_candidate(row, row_id)
        require(row["family_id"] in family_by_id, f"{row_id}: unknown family_id")
        require(row["wrapper_id"] in wrapper_by_id, f"{row_id}: unknown wrapper_id")
        family = family_by_id[row["family_id"]]
        wrapper = wrapper_by_id[row["wrapper_id"]]
        require(set(family["effects"]).issubset(set(row["effects"])), f"{row_id}: dropped family effects")
        require(set(wrapper["effects"]).issubset(set(row["effects"])), f"{row_id}: dropped wrapper effects")
        require(set(family["proof_requirements"]).issubset(set(row["proof_requirements"])), f"{row_id}: dropped family proofs")
        require(set(wrapper["proof_requirements"]).issubset(set(row["proof_requirements"])), f"{row_id}: dropped wrapper proofs")
        require(row_id not in resolved_by_id, f"duplicate primitive_id {row_id}")
        resolved_by_id[row_id] = row

    edge_ids = set()
    for row in edges:
        row_id = row.get("edge_id", "<missing-edge-id>")
        require_text(row, row_id, "edge_id", "record_type", "from_primitive_id", "to_primitive_id", "status")
        require(row["record_type"] == "compatibility_edge", f"{row_id}: wrong record_type")
        require_candidate(row, row_id)
        require(row_id not in edge_ids, f"duplicate edge_id {row_id}")
        edge_ids.add(row_id)
        left = resolved_by_id.get(row["from_primitive_id"])
        right = resolved_by_id.get(row["to_primitive_id"])
        require(left is not None, f"{row_id}: unknown from_primitive_id")
        require(right is not None, f"{row_id}: unknown to_primitive_id")
        require(left["edge_signature"]["output_types"][0] == right["edge_signature"]["input_types"][0], f"{row_id}: incompatible type edge")

    route_ids = set()
    for row in routes:
        row_id = row.get("route_template_id", "<missing-route-id>")
        require_text(row, row_id, "route_template_id", "record_type", "input_edge", "output_edge", "compile_policy")
        require(row["record_type"] == "route_template", f"{row_id}: wrong record_type")
        require_candidate(row, row_id)
        require(row_id not in route_ids, f"duplicate route_template_id {row_id}")
        route_ids.add(row_id)
        steps = row.get("route_steps")
        require(isinstance(steps, list) and len(steps) >= 3, f"{row_id}: route needs at least 3 steps")
        for step_id in steps:
            require(step_id in resolved_by_id, f"{row_id}: unknown step {step_id}")
        for left_id, right_id in zip(steps, steps[1:]):
            left = resolved_by_id[left_id]
            right = resolved_by_id[right_id]
            require(
                left["edge_signature"]["output_types"][0] == right["edge_signature"]["input_types"][0],
                f"{row_id}: step chain does not connect {left_id} -> {right_id}",
            )
        require(row.get("required_proofs"), f"{row_id}: missing required_proofs")

    bundle_ids = set()
    for row in bundles:
        row_id = row.get("candidate_bundle_id", "<missing-bundle-id>")
        require_text(row, row_id, "candidate_bundle_id", "record_type", "query", "route_template_id")
        require(row["record_type"] == "candidate_bundle_example", f"{row_id}: wrong record_type")
        require_candidate(row, row_id)
        require(row_id not in bundle_ids, f"duplicate candidate_bundle_id {row_id}")
        bundle_ids.add(row_id)
        require(row["route_template_id"] in route_ids, f"{row_id}: unknown route_template_id")
        candidates = row.get("candidate_primitives")
        require(isinstance(candidates, list) and candidates, f"{row_id}: missing candidate_primitives")
        for item in candidates:
            primitive_id = item.get("primitive_id")
            require(primitive_id in resolved_by_id, f"{row_id}: unknown candidate primitive {primitive_id}")
            require_candidate(item, f"{row_id}:{primitive_id}")

    return {
        "primitive_families": len(families),
        "runtime_wrappers": len(wrappers),
        "resolved_primitives": len(resolved),
        "compatibility_edges": len(edges),
        "route_templates": len(routes),
        "candidate_bundle_examples": len(bundles),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    args = parser.parse_args()
    counts = check_pack(args.pack)
    print(json.dumps({"ok": True, **counts}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
