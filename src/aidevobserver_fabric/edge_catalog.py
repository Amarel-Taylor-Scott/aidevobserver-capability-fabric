"""Search and route over the generated edge primitive catalog."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_CATALOG_DIR = Path("generated/edge_primitive_catalog")
DEFAULT_CATALOG_ZIP = Path("artifacts/edge_primitive_catalog.zip")
ZIP_PREFIX = "generated/edge_primitive_catalog/"
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


@dataclass(frozen=True, slots=True)
class CatalogLocation:
    root: Path = DEFAULT_CATALOG_DIR
    archive: Path = DEFAULT_CATALOG_ZIP


def normalize_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in TOKEN_RE.findall(text.replace(">", " ").replace("[", " ").replace("]", " ")):
        lowered = raw.lower()
        if len(lowered) >= 2:
            tokens.add(lowered)
        for part in lowered.split("_"):
            if len(part) >= 2:
                tokens.add(part)
    return tokens


def _catalog_source(location: CatalogLocation) -> tuple[str, Path]:
    if location.root.exists():
        return ("dir", location.root)
    if location.archive.exists():
        return ("zip", location.archive)
    raise FileNotFoundError(f"missing edge primitive catalog at {location.root} or {location.archive}")


def _read_text(location: CatalogLocation, filename: str) -> str:
    source_kind, source_path = _catalog_source(location)
    if source_kind == "dir":
        return source_path.joinpath(filename).read_text(encoding="utf-8")
    with zipfile.ZipFile(source_path) as zf:
        return zf.read(ZIP_PREFIX + filename).decode("utf-8")


def _iter_jsonl(location: CatalogLocation, filename: str) -> Iterable[dict[str, Any]]:
    source_kind, source_path = _catalog_source(location)
    if source_kind == "dir":
        with source_path.joinpath(filename).open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)
        return
    with zipfile.ZipFile(source_path) as zf:
        with zf.open(ZIP_PREFIX + filename) as fh:
            for raw in fh:
                line = raw.decode("utf-8")
                if line.strip():
                    yield json.loads(line)


def load_manifest(location: CatalogLocation = CatalogLocation()) -> dict[str, Any]:
    return json.loads(_read_text(location, "manifest.json"))


def summary(location: CatalogLocation = CatalogLocation()) -> dict[str, Any]:
    source_kind, source_path = _catalog_source(location)
    manifest = load_manifest(location)
    return {
        "catalog_id": manifest["pack_id"],
        "version": manifest["version"],
        "source": source_kind,
        "source_path": str(source_path),
        "candidate": True,
        "serves_truth": False,
        "files": manifest["files"],
    }


def load_resolved(location: CatalogLocation = CatalogLocation()) -> list[dict[str, Any]]:
    return list(_iter_jsonl(location, "resolved_primitives.jsonl"))


def load_routes(location: CatalogLocation = CatalogLocation()) -> list[dict[str, Any]]:
    return list(_iter_jsonl(location, "route_templates.jsonl"))


def load_edges(location: CatalogLocation = CatalogLocation()) -> list[dict[str, Any]]:
    return list(_iter_jsonl(location, "compatibility_edges.jsonl"))


def row_text(row: dict[str, Any]) -> str:
    problem_solution = row.get("problem_solution") or {}
    return " ".join(
        [
            str(row.get("primitive_id") or row.get("route_template_id") or ""),
            str(row.get("title") or ""),
            str(row_field(row, "domain") or ""),
            str(row_field(row, "data_shape") or ""),
            str(row_field(row, "operation") or ""),
            str(row.get("input_edge") or ""),
            str(row.get("output_edge") or ""),
            " ".join(row.get("effects") or []),
            " ".join(row.get("proof_requirements") or row.get("required_proofs") or []),
            str(problem_solution.get("problem") or ""),
            str(problem_solution.get("solution") or ""),
            str(problem_solution.get("naive_agent_failure") or ""),
        ]
    )


def family_parts(row: dict[str, Any]) -> dict[str, str]:
    family_id = str(row.get("family_id") or "")
    if not family_id.startswith("fam:") or not family_id.endswith("@candidate"):
        return {}
    parts = family_id.removeprefix("fam:").removesuffix("@candidate").split(".")
    if len(parts) < 3:
        return {}
    return {
        "domain": parts[0],
        "data_shape": parts[1],
        "operation": ".".join(parts[2:]),
    }


def row_field(row: dict[str, Any], field: str) -> Any:
    if field in row:
        return row[field]
    return family_parts(row).get(field)


def score_row(row: dict[str, Any], query_terms: set[str], filters: dict[str, str | None]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    text_terms = normalize_tokens(row_text(row))
    overlap = len(query_terms & text_terms)
    if query_terms:
        score += overlap / len(query_terms)
    if overlap:
        reasons.append(f"term_overlap:{overlap}")
    for field, value in filters.items():
        if value is None:
            continue
        row_value = row_field(row, field)
        if row_value == value:
            score += 1.0
            reasons.append(f"{field}:exact")
        elif isinstance(row_value, list) and value in row_value:
            score += 0.8
            reasons.append(f"{field}:contains")
        else:
            return (0.0, [])
    return (score, reasons)


def search_primitives(
    query: str,
    *,
    domain: str | None = None,
    data_shape: str | None = None,
    operation: str | None = None,
    runtime_target: str | None = None,
    limit: int = 10,
    location: CatalogLocation = CatalogLocation(),
) -> dict[str, Any]:
    query_terms = normalize_tokens(query)
    filters = {
        "domain": domain,
        "data_shape": data_shape,
        "operation": operation,
        "runtime_targets": runtime_target,
    }
    scored: list[tuple[float, str, dict[str, Any], list[str]]] = []
    for row in load_resolved(location):
        score, reasons = score_row(row, query_terms, filters)
        if score <= 0:
            continue
        scored.append((score, row["primitive_id"], row, reasons))
    scored.sort(key=lambda item: (-item[0], item[1]))
    results = []
    for score, _, row, reasons in scored[:limit]:
        results.append(
            {
                "primitive_id": row["primitive_id"],
                "title": row["title"],
                "input_edge": row["input_edge"],
                "output_edge": row["output_edge"],
                "runtime_targets": row["runtime_targets"],
                "effects": row["effects"],
                "proof_requirements": row["proof_requirements"],
                "score": round(score, 6),
                "reasons": reasons,
                "candidate": True,
                "serves_truth": False,
            }
        )
    return {
        "query": query,
        "filters": {key: value for key, value in filters.items() if value is not None},
        "count": len(results),
        "results": results,
        "candidate": True,
        "serves_truth": False,
    }


def search_routes(
    query: str,
    *,
    domain: str | None = None,
    data_shape: str | None = None,
    pattern: str | None = None,
    limit: int = 10,
    location: CatalogLocation = CatalogLocation(),
) -> dict[str, Any]:
    query_terms = normalize_tokens(query)
    filters = {
        "domain": domain,
        "data_shape": data_shape,
        "pattern": pattern,
    }
    scored: list[tuple[float, str, dict[str, Any], list[str]]] = []
    for row in load_routes(location):
        score, reasons = score_row(row, query_terms, filters)
        if score <= 0:
            continue
        scored.append((score, row["route_template_id"], row, reasons))
    scored.sort(key=lambda item: (-item[0], item[1]))
    results = []
    for score, _, row, reasons in scored[:limit]:
        results.append(
            {
                "route_template_id": row["route_template_id"],
                "title": row["title"],
                "input_edge": row["input_edge"],
                "output_edge": row["output_edge"],
                "pattern": row["pattern"],
                "route_steps": row["route_steps"],
                "required_proofs": row["required_proofs"],
                "score": round(score, 6),
                "reasons": reasons,
                "candidate": True,
                "serves_truth": False,
            }
        )
    return {
        "query": query,
        "filters": {key: value for key, value in filters.items() if value is not None},
        "count": len(results),
        "results": results,
        "candidate": True,
        "serves_truth": False,
    }


def route_planlock(route: dict[str, Any], resolved_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    steps = [resolved_by_id[primitive_id] for primitive_id in route["route_steps"]]
    canonical = {
        "route_template_id": route["route_template_id"],
        "route_steps": route["route_steps"],
        "input_edge": route["input_edge"],
        "output_edge": route["output_edge"],
    }
    route_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    effects = sorted({effect for step in steps for effect in step.get("effects", [])})
    proofs = sorted({proof for step in steps for proof in step.get("proof_requirements", [])})
    return {
        "planlock_id": f"lock:{route['route_template_id'].removeprefix('route:').removesuffix('@candidate')}@candidate",
        "route_template_id": route["route_template_id"],
        "input_edge": route["input_edge"],
        "output_edge": route["output_edge"],
        "route_hash": f"sha256:{route_hash}",
        "route_steps": [
            {
                "step_index": index,
                "primitive_id": step["primitive_id"],
                "input_edge": step["input_edge"],
                "output_edge": step["output_edge"],
                "runtime_targets": step["runtime_targets"],
            }
            for index, step in enumerate(steps)
        ],
        "effect_policy": {
            "declared_effects": effects,
            "write_effects_require_explicit_execution_policy": any("write" in effect for effect in effects),
        },
        "proof_requirements": proofs,
        "compile_policy": route["compile_policy"],
        "candidate": True,
        "serves_truth": False,
    }


def best_route_planlock(
    query: str,
    *,
    domain: str | None = None,
    data_shape: str | None = None,
    pattern: str | None = None,
    location: CatalogLocation = CatalogLocation(),
) -> dict[str, Any]:
    route_results = search_routes(
        query,
        domain=domain,
        data_shape=data_shape,
        pattern=pattern,
        limit=1,
        location=location,
    )
    if not route_results["results"]:
        return {
            "error": "no_route_template_found",
            "query": query,
            "candidate": True,
            "serves_truth": False,
        }
    route_id = route_results["results"][0]["route_template_id"]
    routes = {route["route_template_id"]: route for route in load_routes(location)}
    resolved_by_id = {row["primitive_id"]: row for row in load_resolved(location)}
    planlock = route_planlock(routes[route_id], resolved_by_id)
    planlock["selected_by"] = route_results["results"][0]
    return planlock


def graph_route(
    start_type: str,
    end_type: str,
    *,
    max_depth: int = 8,
    limit: int = 3,
    location: CatalogLocation = CatalogLocation(),
) -> dict[str, Any]:
    resolved_by_id = {row["primitive_id"]: row for row in load_resolved(location)}
    start_ids = [
        primitive_id
        for primitive_id, row in resolved_by_id.items()
        if row["edge_signature"]["input_types"][0] == start_type
    ]
    end_ids = {
        primitive_id
        for primitive_id, row in resolved_by_id.items()
        if row["edge_signature"]["output_types"][0] == end_type
    }
    adjacency: dict[str, list[str]] = {}
    for edge in load_edges(location):
        adjacency.setdefault(edge["from_primitive_id"], []).append(edge["to_primitive_id"])

    found: list[list[str]] = []
    queue: deque[list[str]] = deque([[_id] for _id in sorted(start_ids)[:200]])
    while queue and len(found) < limit:
        path = queue.popleft()
        last = path[-1]
        if last in end_ids:
            found.append(path)
            continue
        if len(path) >= max_depth:
            continue
        for next_id in sorted(adjacency.get(last, []))[:50]:
            if next_id not in path:
                queue.append([*path, next_id])

    return {
        "start_type": start_type,
        "end_type": end_type,
        "max_depth": max_depth,
        "routes": [
            {
                "route_hash": "sha256:" + hashlib.sha256("|".join(path).encode("utf-8")).hexdigest(),
                "route_steps": path,
                "candidate": True,
                "serves_truth": False,
            }
            for path in found
        ],
        "candidate": True,
        "serves_truth": False,
    }


def compact_search(result: dict[str, Any]) -> str:
    lines = [
        "AIDevObserver edge catalog search",
        f"Q {result['query']}",
        "BOUNDARY candidate=true serves_truth=false",
    ]
    for index, item in enumerate(result["results"][:5], start=1):
        lines.append(
            f"TOP{index} {item['primitive_id']} score:{item['score']} "
            f"{item['input_edge']}>{item['output_edge']}"
        )
    return "\n".join(lines) + "\n"
