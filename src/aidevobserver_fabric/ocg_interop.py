"""End-to-end Open Capability Graph interoperability bakeoff.

This module joins the loss-aware native importers, conservative directional
compatibility checker, and portable two-backend retrieval runner.  Its output
is an executed research receipt.  It does not promote imported actions,
search hits, or structurally compatible schemas to execution authorization.
"""

from __future__ import annotations

from base64 import b64encode
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

import jsonschema

from .ocg_compatibility import (
    BenchmarkCase,
    CompatibilityStatus,
    run_held_out_benchmark,
)
from .ocg_conformance import validate_document
from .ocg_importers import (
    OCGImportResult,
    SCHEMA_URI,
    import_agent_spec,
    import_cwl,
    import_mcp_tools,
    import_openapi,
    import_wit_json,
)
from .ocg_search_bakeoff import QueryVector, run_search_bakeoff


BAKEOFF_VERSION = "ocg-interoperability-bakeoff/0.1"
INTEROP_COMPATIBILITY_BENCHMARK_ID = "ocg-interoperability-projection-pairs-v0.1"
FIXED_GENERATED_AT = "2026-07-11T00:00:00Z"
TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)*")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _data_uri(payload: bytes, media_type: str = "application/json") -> str:
    return f"data:{media_type};base64,{b64encode(payload).decode('ascii')}"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _distribution_receipt(name: str) -> dict[str, Any]:
    """Identify an installed Python distribution without claiming a wheel digest."""

    distribution = importlib.metadata.distribution(name)
    receipt: dict[str, Any] = {"version": distribution.version}
    record = distribution.read_text("RECORD")
    if record is not None:
        receipt["installed_record_digest"] = _digest(record.encode("utf-8"))
    metadata = distribution.read_text("METADATA")
    if metadata is not None:
        receipt["metadata_digest"] = _digest(metadata.encode("utf-8"))
    return receipt


def _input_receipt(fixtures_dir: Path, schema_path: Path) -> dict[str, Any]:
    fixture_manifest = _load_json(fixtures_dir / "manifest.json")
    fixture_names = {"manifest.json"}
    for source in fixture_manifest.get("sources", []):
        if not isinstance(source, Mapping):
            continue
        for field_name in ("path", "normalized_path"):
            value = source.get(field_name)
            if isinstance(value, str):
                fixture_names.add(value)

    def file_receipt(path: Path, name: str) -> dict[str, Any]:
        payload = path.read_bytes()
        return {"name": name, "digest": _digest(payload), "bytes": len(payload)}

    module_root = Path(__file__).resolve().parent
    module_names = (
        "ocg_compatibility.py",
        "ocg_conformance.py",
        "ocg_importers.py",
        "ocg_interop.py",
        "ocg_search_bakeoff.py",
    )
    return {
        "fixtures": [
            file_receipt(fixtures_dir / name, name) for name in sorted(fixture_names)
        ],
        "ocg_schema": file_receipt(schema_path, schema_path.name),
        "implementation_modules": [
            file_receipt(module_root / name, name) for name in module_names
        ],
        "closure_boundary": (
            "Exact fixture, schema, and local module bytes are bound here. Python package "
            "RECORD/METADATA fingerprints and the wasm-tools binary digest are recorded "
            "separately; this is not a complete environment lock or wheel provenance claim."
        ),
    }


def import_interoperability_fixtures(fixtures_dir: Path) -> list[OCGImportResult]:
    """Import the five committed native-format fixtures as candidate graphs."""

    fixtures_dir = fixtures_dir.resolve()
    source_uri = lambda name: f"urn:example:ocg:interop-fixture:{name}"  # noqa: E731
    fixture_manifest = _load_json(fixtures_dir / "manifest.json")
    wit_fixture = next(
        row for row in fixture_manifest["sources"] if row.get("format") == "wit"
    )
    return [
        import_mcp_tools(
            _load_json(fixtures_dir / "mcp-tools.json"),
            source_uri=source_uri("mcp-tools.json"),
        ),
        import_openapi(
            _load_json(fixtures_dir / "openapi-customer.json"),
            source_uri=source_uri("openapi-customer.json"),
        ),
        import_cwl(
            _load_json(fixtures_dir / "cwl-emit-json.json"),
            source_uri=source_uri("cwl-emit-json.json"),
        ),
        import_wit_json(
            _load_json(fixtures_dir / "customer.wit.json"),
            source_uri=source_uri("customer.wit"),
            raw_wit=(fixtures_dir / "customer.wit").read_bytes(),
            normalizer={
                "id": wit_fixture["normalizer"],
                "version": wit_fixture["normalizer_version"],
                "binary_digest": wit_fixture["normalizer_binary_digest"],
                "binary_size_bytes": wit_fixture["normalizer_binary_size_bytes"],
                "binary_uri": wit_fixture["normalizer_binary_uri"],
            },
        ),
        import_agent_spec(
            _load_json(fixtures_dir / "agent-spec-customer.json"),
            source_uri=source_uri("agent-spec-customer.json"),
        ),
    ]


def _words(text: str) -> list[str]:
    return [token.lower().replace("_", "-") for token in TOKEN_RE.findall(text)]


def _character_trigrams(text: str) -> list[str]:
    normalized = " ".join(_words(text))
    padded = f"  {normalized}  "
    return [padded[index : index + 3] for index in range(max(0, len(padded) - 2))]


def _feature_hash(features: Iterable[str], dimensions: int = 32) -> list[float]:
    vector = [0.0] * dimensions
    for feature in features:
        raw = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(raw[:4], "big") % dimensions
        sign = -1.0 if raw[4] & 1 else 1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    return [_float32(value / norm) for value in vector] if norm else vector


def _float32(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", value))[0]


def _sparse_vector(text: str, vocabulary: Mapping[str, int]) -> dict[str, list[Any]]:
    counts: dict[int, float] = {}
    for token in _words(text):
        if token in vocabulary:
            index = vocabulary[token]
            counts[index] = counts.get(index, 0.0) + 1.0
    norm = math.sqrt(sum(value * value for value in counts.values()))
    indices = sorted(counts)
    values = [_float32(counts[index] / norm) for index in indices] if norm else []
    return {"indices": indices, "values": values}


def _projection_artifact(name: str, specification: Mapping[str, Any]) -> dict[str, Any]:
    payload = _json_bytes(specification)
    return {
        "id": f"urn:example:ocg:artifact:interop-projection:{name}",
        "digest": _digest(payload),
        "media_type": "application/json",
        "size_bytes": len(payload),
        "locators": [{"uri": _data_uri(payload), "priority": 0}],
        "lifecycle": "active",
        "metadata": {"boundary": "deterministic_nonlearned_retrieval_projection"},
    }


def _capability_text(
    capability: Mapping[str, Any],
    action: Mapping[str, Any],
    implementation: Mapping[str, Any],
) -> str:
    port_labels = " ".join(str(row.get("label") or row.get("id") or "") for row in action.get("ports", []))
    source_format = implementation.get("metadata", {}).get("source_format", "")
    return " ".join(
        part
        for part in (
            str(capability.get("label") or ""),
            str(capability.get("description") or ""),
            str(action.get("label") or ""),
            str(action.get("description") or ""),
            port_labels,
            str(source_format),
        )
        if part
    )


def build_interoperability_retrieval_graph(
    imports: Sequence[OCGImportResult],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Merge imported candidates and add three executed retrieval projections."""

    nodes: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    imported_artifacts: list[dict[str, Any]] = []
    import_summary: list[dict[str, Any]] = []
    for result in imports:
        document = result.document
        nodes.extend(deepcopy(document.get("nodes", [])))
        actions.extend(deepcopy(document.get("actions", [])))
        relations.extend(deepcopy(document.get("relations", [])))
        imported_artifacts.extend(deepcopy(document.get("artifacts", [])))
        import_summary.append(
            {
                "source_format": result.source_format,
                "source_digest": result.source_digest,
                "action_count": len(document.get("actions", [])),
                "warning_count": len(result.warnings),
                "planning_eligibility": result.planning_eligibility,
            }
        )

    node_index = {row["id"]: row for row in nodes}
    action_by_capability = {row["capability_ref"]: row for row in actions}
    capabilities = [row for row in nodes if row.get("kind") == "capability"]
    texts: dict[str, str] = {}
    for capability in capabilities:
        action = action_by_capability[capability["id"]]
        implementation = node_index[action["implementation_ref"]]
        text = _capability_text(capability, action, implementation)
        texts[capability["id"]] = text
        capability["digest"] = _digest(text.encode("utf-8"))
        capability.setdefault("metadata", {})["retrieval_projection_boundary"] = (
            "candidate_generation_only"
        )

    vocabulary_terms = sorted({token for text in texts.values() for token in _words(text)})
    vocabulary = {token: index for index, token in enumerate(vocabulary_terms)}
    vocabulary_digest = _digest(_json_bytes(vocabulary_terms))

    tokenization = {
        "input": "Unicode string",
        "regex": TOKEN_RE.pattern,
        "regex_character_classes": "ASCII ranges written explicitly; Python Unicode regex mode",
        "matching": "left-to-right non-overlapping findall",
        "transform": ["ASCII lowercase", "replace underscore with hyphen"],
        "output_order": "encounter order with duplicates preserved",
    }
    feature_hash = {
        "hash": "sha256",
        "feature_encoding": "UTF-8",
        "bucket": "unsigned big-endian digest bytes 0..3 modulo dimensions",
        "sign": "digest byte 4 low bit: 1 => -1.0, 0 => +1.0",
        "accumulation": "signed count per bucket",
        "normalization": "L2 over accumulated vector",
        "quantization": "IEEE-754 binary32 after normalization",
    }

    recipe_specs = {
        "word-hash": {
            "recipe_version": "ocg-deterministic-projection/0.1",
            "algorithm": "signed-sha256-feature-hash",
            "tokenization": tokenization,
            "features": "one feature per normalized token",
            "feature_hash": feature_hash,
            "dimensions": 32,
            "normalization": "l2",
            "dtype": "float32",
            "learned": False,
        },
        "char-hash": {
            "recipe_version": "ocg-deterministic-projection/0.1",
            "algorithm": "signed-sha256-feature-hash",
            "tokenization": tokenization,
            "features": {
                "join": "single ASCII space",
                "padding": "two ASCII spaces on each side",
                "window": "all overlapping 3-code-point windows in encounter order",
            },
            "feature_hash": feature_hash,
            "dimensions": 32,
            "normalization": "l2",
            "dtype": "float32",
            "learned": False,
        },
        "token-sparse": {
            "recipe_version": "ocg-deterministic-projection/0.1",
            "algorithm": "corpus-snapshot-token-count",
            "tokenization": tokenization,
            "vocabulary": vocabulary_terms,
            "vocabulary_digest": vocabulary_digest,
            "indexing": "zero-based index in the stored vocabulary array",
            "dimensions": len(vocabulary),
            "normalization": "l2",
            "dtype": "sparse_float32",
            "learned": False,
        },
    }
    projection_artifacts = [
        _projection_artifact(name, spec) for name, spec in recipe_specs.items()
    ]
    artifacts = [*imported_artifacts, *projection_artifacts]
    artifact_by_name = {
        row["id"].rsplit(":", 1)[-1]: row for row in projection_artifacts
    }
    space_by_name = {
        name: f"urn:example:ocg:space:projection:{artifact['digest'].split(':', 1)[1]}"
        for name, artifact in artifact_by_name.items()
    }

    representations: list[dict[str, Any]] = []
    rep_ids: dict[str, list[str]] = {"lexical": [], "word-hash": [], "char-hash": [], "token-sparse": []}
    for capability in capabilities:
        subject_id = capability["id"]
        text = texts[subject_id]
        stable = uuid5(NAMESPACE_URL, f"ocg-interop-representation\x00{subject_id}")
        lexical_id = f"urn:uuid:{uuid5(stable, 'lexical')}"
        representations.append(
            {
                "id": lexical_id,
                "subject_ref": subject_id,
                "view_kind": "urn:example:ocg:view:intent-and-contract-labels",
                "source_digest": capability["digest"],
                "modality": "text",
                "encoding": "lexical",
                "text": text,
                "lifecycle": "candidate",
                "metadata": {"source": "loss-aware-native-import", "learned": False},
            }
        )
        rep_ids["lexical"].append(lexical_id)
        vector_rows = (
            ("word-hash", space_by_name["word-hash"], _feature_hash(_words(text))),
            ("char-hash", space_by_name["char-hash"], _feature_hash(_character_trigrams(text))),
        )
        for name, space_id, vector in vector_rows:
            rep_id = f"urn:uuid:{uuid5(stable, name)}"
            artifact = artifact_by_name[name]
            representations.append(
                {
                    "id": rep_id,
                    "subject_ref": subject_id,
                    "view_kind": "urn:example:ocg:view:intent-and-contract-labels",
                    "source_digest": capability["digest"],
                    "modality": "text",
                    "encoding": "dense_vector",
                    "projection_recipe": {"id": artifact["id"], "digest": artifact["digest"]},
                    "embedding": {
                        "space_id": space_id,
                        "model": {
                            "id": f"urn:example:ocg:model:{name}:v1",
                            "revision": "1",
                            "task": "symmetric",
                        },
                        "dimensions": 32,
                        "dtype": "float32",
                        "normalization": "l2",
                        "distance": "cosine",
                        "generation": {
                            "generated_at": FIXED_GENERATED_AT,
                            "generator": f"aidevobserver-ocg-{name}-v1",
                        },
                        "vector": vector,
                    },
                    "lifecycle": "candidate",
                    "metadata": {"learned": False, "authorization_role": "none"},
                }
            )
            rep_ids[name].append(rep_id)

        sparse_id = f"urn:uuid:{uuid5(stable, 'token-sparse')}"
        sparse_artifact = artifact_by_name["token-sparse"]
        representations.append(
            {
                "id": sparse_id,
                "subject_ref": subject_id,
                "view_kind": "urn:example:ocg:view:intent-and-contract-labels",
                "source_digest": capability["digest"],
                "modality": "text",
                "encoding": "sparse_vector",
                "projection_recipe": {
                    "id": sparse_artifact["id"],
                    "digest": sparse_artifact["digest"],
                },
                "embedding": {
                    "space_id": space_by_name["token-sparse"],
                    "model": {
                        "id": "urn:example:ocg:model:token-count-v1",
                        "revision": vocabulary_digest,
                        "task": "symmetric",
                    },
                    "dimensions": len(vocabulary),
                    "dtype": "sparse_float32",
                    "normalization": "l2",
                    "distance": "cosine",
                    "generation": {
                        "generated_at": FIXED_GENERATED_AT,
                        "generator": "aidevobserver-ocg-token-count-v1",
                    },
                    "vector": _sparse_vector(text, vocabulary),
                },
                "lifecycle": "candidate",
                "metadata": {"learned": False, "authorization_role": "none"},
            }
        )
        rep_ids["token-sparse"].append(sparse_id)

    profile = {
        "id": "urn:example:ocg:search-profile:interop-hybrid-v1",
        "version": "0.1.0",
        "created_at": FIXED_GENERATED_AT,
        "description": "Portable candidate retrieval across lexical and three explicit non-learned vector spaces.",
        "status": "candidate",
        "hard_gates": [
            {"field": "lifecycle", "operator": "not_in", "value": ["revoked", "rejected"]}
        ],
        "stages": [
            {
                "id": "lexical",
                "kind": "lexical",
                "representation_refs": rep_ids["lexical"],
                "query_view": "urn:example:ocg:view:intent-and-contract-labels",
                "candidate_limit": 50,
            },
            {
                "id": "word-hash",
                "kind": "dense_vector",
                "representation_refs": rep_ids["word-hash"],
                "query_view": "urn:example:ocg:view:intent-and-contract-labels",
                "candidate_limit": 50,
            },
            {
                "id": "char-hash",
                "kind": "dense_vector",
                "representation_refs": rep_ids["char-hash"],
                "query_view": "urn:example:ocg:view:intent-and-contract-labels",
                "candidate_limit": 50,
            },
            {
                "id": "token-sparse",
                "kind": "sparse_vector",
                "representation_refs": rep_ids["token-sparse"],
                "query_view": "urn:example:ocg:view:intent-and-contract-labels",
                "candidate_limit": 50,
            },
        ],
        "fusion": {
            "method": "rrf",
            "inputs": [
                {"stage_ref": "lexical", "weight": 1.0},
                {"stage_ref": "word-hash", "weight": 0.8},
                {"stage_ref": "char-hash", "weight": 0.6},
                {"stage_ref": "token-sparse", "weight": 0.8},
            ],
            "parameters": {
                "rrf_k": 60,
                "weights_are_query_preferences_not_truth": True,
                "raw_cross_space_scores_are_not_mixed": True,
            },
        },
        "output": {
            "limit": 4,
            "include_fields": ["label", "description", "lifecycle", "metadata"],
        },
        "metadata": {
            "execution_authorization": "not_evaluated",
            "learned_embedding_models_executed": False,
        },
    }
    document = {
        "$schema": SCHEMA_URI,
        "spec_version": "0.1.0-draft",
        "graph_id": "urn:example:ocg:interoperability-bakeoff-corpus",
        "title": "OCG native-format interoperability retrieval corpus",
        "description": "Candidate-only merge of five loss-aware native imports with deterministic retrieval projections.",
        "status": "candidate",
        "profiles": ["core", "retrieval"],
        "nodes": nodes,
        "actions": actions,
        "relations": relations,
        "artifacts": artifacts,
        "representations": representations,
        "search_profiles": [profile],
        "extensions": {
            "urn:example:ocg:extension:interop-import-summary": {
                "imports": import_summary,
                "planning_eligibility": "unknown",
                "execution_authorization": "not_established",
            }
        },
    }
    return document, {
        "word_space": space_by_name["word-hash"],
        "char_space": space_by_name["char-hash"],
        "sparse_space": space_by_name["token-sparse"],
        "vocabulary_digest": vocabulary_digest,
        **{f"token:{key}": str(value) for key, value in vocabulary.items()},
    }


def query_vectors(query: str, retrieval_metadata: Mapping[str, str]) -> dict[str, QueryVector]:
    vocabulary = {
        key.removeprefix("token:"): int(value)
        for key, value in retrieval_metadata.items()
        if key.startswith("token:")
    }
    return {
        "word-hash": QueryVector(retrieval_metadata["word_space"], _feature_hash(_words(query))),
        "char-hash": QueryVector(retrieval_metadata["char_space"], _feature_hash(_character_trigrams(query))),
        "token-sparse": QueryVector(
            retrieval_metadata["sparse_space"],
            _sparse_vector(query, vocabulary),
        ),
    }


def _capability_lookup(document: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    actions = {row["capability_ref"]: row for row in document.get("actions", [])}
    nodes = {row["id"]: row for row in document.get("nodes", [])}
    lookup: dict[tuple[str, str], str] = {}
    for capability_id, action in actions.items():
        capability = nodes[capability_id]
        implementation = nodes[action["implementation_ref"]]
        source_format = str(implementation.get("metadata", {}).get("source_format", ""))
        lookup[(source_format, str(capability.get("label", "")))] = capability_id
    return lookup


def search_queries(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    lookup = _capability_lookup(document)
    return [
        {
            "id": "normalize-customer",
            "query": "normalize customer name and email",
            "relevant_ids": [
                lookup[("mcp-tools", "Normalize customer")],
                lookup[("wit", "normalize-customer")],
            ],
        },
        {
            "id": "adapt-for-export",
            "query": "adapt normalized customer to export field vocabulary",
            "relevant_ids": [lookup[("openapi", "Adapt a normalized customer to the export field vocabulary")]],
        },
        {
            "id": "emit-json",
            "query": "serialize export customer as deterministic json",
            "relevant_ids": [
                lookup[("mcp-tools", "Emit customer JSON")],
                lookup[("cwl", "Emit customer JSON")],
            ],
        },
        {
            "id": "validate-customer",
            "query": "validate a normalized customer record",
            "relevant_ids": [lookup[("agent-spec", "validate_customer")]],
        },
    ]


def _retrieval_metrics(returned_ids: Sequence[str], relevant_ids: Sequence[str]) -> dict[str, Any]:
    relevant = set(relevant_ids)
    returned = list(returned_ids)
    hits = [identifier for identifier in returned if identifier in relevant]
    reciprocal_rank = 0.0
    for index, identifier in enumerate(returned, start=1):
        if identifier in relevant:
            reciprocal_rank = 1.0 / index
            break
    return {
        "relevant_count": len(relevant),
        "hit_count": len(set(hits)),
        "recall_at_returned_k": len(set(hits)) / len(relevant) if relevant else 1.0,
        "reciprocal_rank": reciprocal_rank,
        "top1_relevant": bool(returned and returned[0] in relevant),
    }


def run_portable_search_bakeoff(
    document: Mapping[str, Any], retrieval_metadata: Mapping[str, str]
) -> dict[str, Any]:
    query_receipts = []
    recalls: dict[str, list[float]] = {"reference": [], "sqlite_fts5": []}
    reciprocal_ranks: dict[str, list[float]] = {"reference": [], "sqlite_fts5": []}
    top1_results: dict[str, list[float]] = {"reference": [], "sqlite_fts5": []}
    agreements: list[float] = []
    rank_displacements: list[float] = []
    exact_order_matches: list[float] = []
    top1_matches: list[float] = []
    for query in search_queries(document):
        result = run_search_bakeoff(
            document,
            query_text=query["query"],
            query_vectors=query_vectors(query["query"], retrieval_metadata),
        )
        backend_metrics = {}
        for backend in ("reference", "sqlite_fts5"):
            returned_ids = result["runs"][backend]["receipt"]["returned_ids"]
            metrics = _retrieval_metrics(returned_ids, query["relevant_ids"])
            backend_metrics[backend] = metrics
            recalls[backend].append(metrics["recall_at_returned_k"])
            reciprocal_ranks[backend].append(metrics["reciprocal_rank"])
            top1_results[backend].append(float(metrics["top1_relevant"]))
        agreements.append(result["agreement"]["jaccard"])
        displacement = result["agreement"]["mean_absolute_rank_displacement"]
        if isinstance(displacement, (int, float)):
            rank_displacements.append(float(displacement))
        exact_order_matches.append(float(result["agreement"]["exact_order_match"]))
        top1_matches.append(float(result["agreement"]["top1_match"]))
        query_receipts.append(
            {
                "query_id": query["id"],
                "query": query["query"],
                "relevant_ids": query["relevant_ids"],
                "backend_metrics": backend_metrics,
                "bakeoff": result,
            }
        )
    return {
        "query_count": len(query_receipts),
        "backends": ["reference", "sqlite_fts5"],
        "portability_scope": {
            "independent_components": ["lexical candidate generation"],
            "shared_components": [
                "structured filtering",
                "explicit dense vector scoring",
                "explicit sparse vector scoring",
                "rank fusion",
                "output projection",
            ],
            "full_stack_backend_independence": False,
        },
        "aggregate": {
            backend: {
                "mean_recall_at_returned_k": sum(recalls[backend]) / len(recalls[backend]),
                "mean_reciprocal_rank": sum(reciprocal_ranks[backend]) / len(reciprocal_ranks[backend]),
                "top1_accuracy": sum(top1_results[backend]) / len(top1_results[backend]),
            }
            for backend in recalls
        },
        "mean_backend_jaccard": sum(agreements) / len(agreements),
        "backend_agreement": {
            "top1_match_rate": sum(top1_matches) / len(top1_matches),
            "exact_order_match_rate": sum(exact_order_matches) / len(exact_order_matches),
            "mean_absolute_rank_displacement": (
                sum(rank_displacements) / len(rank_displacements)
                if rank_displacements
                else None
            ),
            "rank_displacement_observed_query_fraction": (
                len(rank_displacements) / len(query_receipts)
            ),
        },
        "queries": query_receipts,
        "candidate_only": True,
        "execution_authorization": "not_evaluated",
        "learned_embeddings_executed": False,
    }


def interoperability_compatibility_cases(fixtures_dir: Path) -> list[BenchmarkCase]:
    """Cross-format cases using explicit benchmark-selected JSON Schema views."""

    mcp = _load_json(fixtures_dir / "mcp-tools.json")
    openapi = _load_json(fixtures_dir / "openapi-customer.json")
    agentspec = _load_json(fixtures_dir / "agent-spec-customer.json")
    normalized = openapi["components"]["schemas"]["NormalizedCustomer"]
    export = openapi["components"]["schemas"]["ExportCustomer"]
    validation_error = openapi["components"]["schemas"]["ValidationError"]
    return [
        BenchmarkCase(
            "mcp-normalized-to-openapi-normalized",
            CompatibilityStatus.SAFE,
            mcp["tools"][0]["outputSchema"],
            normalized,
            description="Explicit JSON Schema projection selected by the benchmark.",
        ),
        BenchmarkCase(
            "openapi-export-to-mcp-emitter",
            CompatibilityStatus.SAFE,
            export,
            mcp["tools"][1]["inputSchema"],
            description=(
                "Manually selected OpenAPI 200/application-json ExportCustomer component "
                "projection. This does not qualify response-status selection or the whole operation."
            ),
        ),
        BenchmarkCase(
            "mcp-normalized-to-mcp-export-emitter",
            CompatibilityStatus.INCOMPATIBLE,
            mcp["tools"][0]["outputSchema"],
            mcp["tools"][1]["inputSchema"],
            description=(
                "Property-name mismatch: the producer may omit required email_address and "
                "emits email, which the closed consumer schema forbids."
            ),
        ),
        BenchmarkCase(
            "mcp-normalized-to-agent-spec-validator",
            CompatibilityStatus.SAFE,
            mcp["tools"][0]["outputSchema"],
            agentspec["tools"][0]["inputs"][0],
            description="Agent Spec property uses a JSON Schema-shaped property contract.",
        ),
        BenchmarkCase(
            "openapi-error-to-mcp-emitter",
            CompatibilityStatus.INCOMPATIBLE,
            validation_error,
            mcp["tools"][1]["inputSchema"],
            description=(
                "Manually selected OpenAPI 422/application-json ValidationError component "
                "cannot satisfy an export customer input."
            ),
        ),
        BenchmarkCase(
            "openapi-unresolved-export-ref-to-mcp-emitter",
            CompatibilityStatus.UNKNOWN,
            openapi["paths"]["/customers/export"]["post"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"],
            mcp["tools"][1]["inputSchema"],
            description=(
                "The raw OpenAPI 200/application-json payload is an unresolved $ref. "
                "The conservative subset must abstain rather than infer the target component."
            ),
        ),
    ]


def validate_native_fixtures(
    fixtures_dir: Path,
    *,
    validator_path: Path | None = None,
    wasm_tools: Path | None = None,
) -> dict[str, Any]:
    """Run installed native validators and return exact pass/unavailable receipts."""

    original_sys_path = list(sys.path)
    if validator_path is not None:
        resolved = str(validator_path.resolve())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)
    try:
        return _validate_native_fixtures_scoped(
            fixtures_dir,
            validator_path=validator_path,
            wasm_tools=wasm_tools,
        )
    finally:
        sys.path[:] = original_sys_path


def _redacted_error(
    exc: Exception,
    *,
    fixtures_dir: Path,
    validator_path: Path | None,
    wasm_tools: Path | None,
) -> str:
    message = str(exc).replace(str(fixtures_dir.resolve()), "<fixtures>")
    if validator_path is not None:
        message = message.replace(str(validator_path), "<validator-path>")
        message = message.replace(str(validator_path.resolve()), "<validator-path>")
    if wasm_tools is not None:
        message = message.replace(str(wasm_tools), "<wasm-tools>")
        message = message.replace(str(wasm_tools.resolve()), "<wasm-tools>")
    return message


def _validate_native_fixtures_scoped(
    fixtures_dir: Path,
    *,
    validator_path: Path | None,
    wasm_tools: Path | None,
) -> dict[str, Any]:
    receipts: dict[str, Any] = {}

    mcp = _load_json(fixtures_dir / "mcp-tools.json")
    try:
        for tool in mcp["tools"]:
            jsonschema.Draft202012Validator.check_schema(tool["inputSchema"])
            jsonschema.Draft202012Validator.check_schema(tool["outputSchema"])
    except Exception as exc:  # pragma: no cover - receipt path
        receipts["mcp"] = {
            "status": "failed",
            "check_kind": "json-schema-metaschema",
            "error": _redacted_error(
                exc,
                fixtures_dir=fixtures_dir,
                validator_path=validator_path,
                wasm_tools=wasm_tools,
            ),
        }
    else:
        receipts["mcp"] = {
            "status": "passed",
            "validator": "jsonschema.Draft202012Validator.check_schema",
            "check_kind": "json-schema-metaschema",
            "scope": "four tool schemas (input and output for two tools); no official MCP document validator claimed",
            **_distribution_receipt("jsonschema"),
        }

    try:
        from openapi_spec_validator import validate

        validate(_load_json(fixtures_dir / "openapi-customer.json"))
        receipts["openapi"] = {
            "status": "passed",
            "validator": "openapi-spec-validator",
            "check_kind": "full-document-validation",
            "scope": "complete committed OpenAPI fixture",
            **_distribution_receipt("openapi-spec-validator"),
        }
    except ModuleNotFoundError as exc:
        if exc.name != "openapi_spec_validator":
            receipts["openapi"] = {
                "status": "failed",
                "check_kind": "full-document-validation",
                "error": _redacted_error(
                    exc,
                    fixtures_dir=fixtures_dir,
                    validator_path=validator_path,
                    wasm_tools=wasm_tools,
                ),
            }
        else:
            receipts["openapi"] = {"status": "unavailable", "validator": "openapi-spec-validator"}
    except ImportError as exc:
        receipts["openapi"] = {
            "status": "failed",
            "check_kind": "full-document-validation",
            "error": _redacted_error(
                exc,
                fixtures_dir=fixtures_dir,
                validator_path=validator_path,
                wasm_tools=wasm_tools,
            ),
        }
    except Exception as exc:  # pragma: no cover - receipt path
        receipts["openapi"] = {
            "status": "failed",
            "check_kind": "full-document-validation",
            "error": _redacted_error(
                exc,
                fixtures_dir=fixtures_dir,
                validator_path=validator_path,
                wasm_tools=wasm_tools,
            ),
        }

    try:
        from cwl_utils.parser import load_document_by_uri

        parsed = load_document_by_uri((fixtures_dir / "cwl-emit-json.json").resolve().as_uri())
        receipts["cwl"] = {
            "status": "passed",
            "validator": "cwl-utils.parser",
            "check_kind": "parse",
            "scope": "complete committed CWL fixture",
            "parsed_type": type(parsed).__name__,
            **_distribution_receipt("cwl-utils"),
        }
    except ModuleNotFoundError as exc:
        if exc.name == "cwl_utils":
            receipts["cwl"] = {"status": "unavailable", "validator": "cwl-utils"}
        else:
            receipts["cwl"] = {
                "status": "failed",
                "check_kind": "parse",
                "error": _redacted_error(
                    exc,
                    fixtures_dir=fixtures_dir,
                    validator_path=validator_path,
                    wasm_tools=wasm_tools,
                ),
            }
    except ImportError as exc:
        receipts["cwl"] = {
            "status": "failed",
            "check_kind": "parse",
            "error": _redacted_error(
                exc,
                fixtures_dir=fixtures_dir,
                validator_path=validator_path,
                wasm_tools=wasm_tools,
            ),
        }
    except Exception as exc:  # pragma: no cover - receipt path
        receipts["cwl"] = {
            "status": "failed",
            "check_kind": "parse",
            "error": _redacted_error(
                exc,
                fixtures_dir=fixtures_dir,
                validator_path=validator_path,
                wasm_tools=wasm_tools,
            ),
        }

    try:
        from pyagentspec.agent import Agent

        agent = Agent.from_json((fixtures_dir / "agent-spec-customer.json").read_text(encoding="utf-8"))
        receipts["agent_spec"] = {
            "status": "passed",
            "validator": "pyagentspec.Agent.from_json",
            "check_kind": "deserialize-and-model-validate",
            "scope": "complete committed Agent Spec fixture",
            "tool_count": len(agent.tools),
            **_distribution_receipt("pyagentspec"),
        }
    except ModuleNotFoundError as exc:
        if exc.name == "pyagentspec":
            receipts["agent_spec"] = {"status": "unavailable", "validator": "pyagentspec"}
        else:
            receipts["agent_spec"] = {
                "status": "failed",
                "check_kind": "deserialize-and-model-validate",
                "error": _redacted_error(
                    exc,
                    fixtures_dir=fixtures_dir,
                    validator_path=validator_path,
                    wasm_tools=wasm_tools,
                ),
            }
    except ImportError as exc:
        receipts["agent_spec"] = {
            "status": "failed",
            "check_kind": "deserialize-and-model-validate",
            "error": _redacted_error(
                exc,
                fixtures_dir=fixtures_dir,
                validator_path=validator_path,
                wasm_tools=wasm_tools,
            ),
        }
    except Exception as exc:  # pragma: no cover - receipt path
        receipts["agent_spec"] = {
            "status": "failed",
            "check_kind": "deserialize-and-model-validate",
            "error": _redacted_error(
                exc,
                fixtures_dir=fixtures_dir,
                validator_path=validator_path,
                wasm_tools=wasm_tools,
            ),
        }

    if wasm_tools is None or not wasm_tools.is_file():
        receipts["wit"] = {
            "status": "unavailable",
            "validator": "wasm-tools component wit --json",
            "check_kind": "parse-normalize-and-compare",
        }
    else:
        try:
            process = subprocess.run(
                [str(wasm_tools), "component", "wit", str(fixtures_dir / "customer.wit"), "--json"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            normalized = json.loads(process.stdout)
            expected = _load_json(fixtures_dir / "customer.wit.json")
            version_process = subprocess.run(
                [str(wasm_tools), "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            binary_digest = _digest(wasm_tools.read_bytes())
            fixture_manifest = _load_json(fixtures_dir / "manifest.json")
            wit_manifest = next(
                row for row in fixture_manifest["sources"] if row.get("format") == "wit"
            )
            provenance_matches = (
                version_process.stdout.strip() == wit_manifest["normalizer_version"]
                and binary_digest == wit_manifest["normalizer_binary_digest"]
                and wasm_tools.stat().st_size
                == wit_manifest["normalizer_binary_size_bytes"]
            )
            receipts["wit"] = {
                "status": (
                    "passed" if normalized == expected and provenance_matches else "failed"
                ),
                "validator": "wasm-tools component wit --json",
                "check_kind": "parse-normalize-and-compare",
                "scope": "raw WIT parses and normalized JSON exactly matches committed projection",
                "version": version_process.stdout.strip(),
                "binary_digest": binary_digest,
                "binary_size_bytes": wasm_tools.stat().st_size,
                "normalized_projection_matches_fixture": normalized == expected,
                "normalizer_provenance_matches_manifest": provenance_matches,
            }
        except Exception as exc:  # pragma: no cover - receipt path
            receipts["wit"] = {
                "status": "failed",
                "check_kind": "parse-normalize-and-compare",
                "error": _redacted_error(
                    exc,
                    fixtures_dir=fixtures_dir,
                    validator_path=validator_path,
                    wasm_tools=wasm_tools,
                ),
            }
    return {
        "aggregate_kind": "heterogeneous-native-format-checks",
        "validators": receipts,
        "all_available": all(row["status"] != "unavailable" for row in receipts.values()),
        "all_passed": all(row["status"] == "passed" for row in receipts.values()),
    }


def _schema_validation(document: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, Any]:
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    errors = sorted(validator.iter_errors(document), key=lambda row: list(row.absolute_path))
    return {
        "valid": not errors,
        "errors": [row.message for row in errors],
    }


def run_interoperability_bakeoff(
    fixtures_dir: Path,
    schema_path: Path,
    *,
    validator_path: Path | None = None,
    wasm_tools: Path | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    imports = import_interoperability_fixtures(fixtures_dir)
    schema = _load_json(schema_path)
    imported_documents: dict[str, dict[str, Any]] = {}
    import_receipts = []
    for result in imports:
        schema_result = _schema_validation(result.document, schema)
        semantic_result = validate_document(result.document).to_dict()
        imported_documents[result.source_format] = result.document
        import_receipts.append(
            {
                "source_format": result.source_format,
                "source_digest": result.source_digest,
                "record_counts": semantic_result["counts"],
                "warning_count": len(result.warnings),
                "warnings": [warning.to_dict() for warning in result.warnings],
                "schema_validation": schema_result,
                "semantic_validation": semantic_result,
                "planning_eligibility": "unknown",
                "execution_authorization": "not_established",
            }
        )

    merged, retrieval_metadata = build_interoperability_retrieval_graph(imports)
    merged_schema = _schema_validation(merged, schema)
    merged_semantic = validate_document(merged).to_dict()
    search = run_portable_search_bakeoff(merged, retrieval_metadata)
    default_compatibility = run_held_out_benchmark().to_dict()
    cross_format_compatibility = run_held_out_benchmark(
        interoperability_compatibility_cases(fixtures_dir),
        benchmark_id=INTEROP_COMPATIBILITY_BENCHMARK_ID,
    ).to_dict()
    native_validation = validate_native_fixtures(
        fixtures_dir,
        validator_path=validator_path,
        wasm_tools=wasm_tools,
    )
    receipt = {
        "receipt_version": BAKEOFF_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "inputs": _input_receipt(fixtures_dir, schema_path),
        "boundary": {
            "inventory_is_not_execution": True,
            "search_scores_authorize_execution": False,
            "structural_compatibility_authorizes_execution": False,
            "learned_embeddings_executed": False,
            "planning_eligibility": "unknown",
        },
        "native_validation": native_validation,
        "imports": import_receipts,
        "merged_graph": {
            "schema_validation": merged_schema,
            "semantic_validation": merged_semantic,
            "counts": merged_semantic["counts"],
            "source_format_count": len(imports),
            "retrieval_projection_count": len(merged.get("representations", [])),
            "vector_space_count": len(
                {
                    row["embedding"]["space_id"]
                    for row in merged.get("representations", [])
                    if "embedding" in row
                }
            ),
        },
        "search_bakeoff": search,
        "compatibility_bakeoff": {
            "default_held_out": default_compatibility,
            "interoperability_explicit_json_schema_projections": cross_format_compatibility,
            "case_composition": {
                "cross_format_pairs": 5,
                "same_format_negative_controls": 1,
                "fixture_authored_labels": True,
                "independent_validation_set": False,
            },
            "projection_boundary": (
                "Interoperability cases use benchmark-selected JSON Schema views. "
                "The importers did not infer or authorize these mappings."
            ),
            "unassessed_native_dialects": ["cwl", "wit"],
        },
    }
    documents = {**imported_documents, "merged-retrieval-graph": merged}
    return receipt, documents


def write_bakeoff_artifacts(
    output_dir: Path,
    receipt: Mapping[str, Any],
    documents: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    for name, document in sorted(documents.items()):
        path = output_dir / f"{name}.ocg.json"
        payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        path.write_text(payload, encoding="utf-8")
        manifest_rows.append(
            {"path": path.name, "digest": _digest(payload.encode("utf-8")), "bytes": len(payload.encode("utf-8"))}
        )
    receipt_path = output_dir / "receipt.json"
    receipt_payload = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    receipt_path.write_text(receipt_payload, encoding="utf-8")
    manifest_rows.append(
        {
            "path": receipt_path.name,
            "digest": _digest(receipt_payload.encode("utf-8")),
            "bytes": len(receipt_payload.encode("utf-8")),
        }
    )
    manifest = {
        "manifest_version": "ocg-interoperability-artifacts/0.1",
        "files": manifest_rows,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_payload = json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    manifest_path.write_text(manifest_payload, encoding="utf-8")
    return {"output_dir": str(output_dir), "manifest": manifest, "manifest_path": str(manifest_path)}


__all__ = [
    "BAKEOFF_VERSION",
    "build_interoperability_retrieval_graph",
    "import_interoperability_fixtures",
    "interoperability_compatibility_cases",
    "query_vectors",
    "run_interoperability_bakeoff",
    "run_portable_search_bakeoff",
    "search_queries",
    "validate_native_fixtures",
    "write_bakeoff_artifacts",
]
