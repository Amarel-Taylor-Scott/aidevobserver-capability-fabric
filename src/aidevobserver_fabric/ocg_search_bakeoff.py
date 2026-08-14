"""Execute an OCG search profile against small, deterministic local backends.

This module is deliberately a retrieval evaluator, not an admission engine.
Search scores and backend agreement are candidate-generation observations only;
they never establish compatibility, planning eligibility, or authorization.

The two backends share profile parsing, filtering, vector scoring, fusion, and
receipt generation.  They differ in how lexical stages are actually executed:

* ``reference`` performs a deterministic Python token scan.
* ``sqlite_fts5`` builds and queries an in-memory SQLite FTS5 index.

No embedding model is invoked.  Vector stages run only when the caller supplies
an explicitly identified query vector in the same declared embedding space.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import platform
import re
import sqlite3
from time import perf_counter_ns
from typing import Any, Iterable, Mapping, Sequence


TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)*")
SEARCHABLE_COLLECTIONS = ("nodes", "actions", "adapters", "artifacts")
INDEXED_COLLECTIONS = (
    "nodes",
    "actions",
    "relations",
    "adapters",
    "artifacts",
    "evidence",
    "representations",
)
VECTOR_STAGE_KINDS = {"dense_vector", "sparse_vector"}
NON_SEARCHABLE_LIFECYCLES = {"revoked", "rejected"}
SUPPORTED_STAGE_KINDS = {
    "structured_filter",
    "lexical",
    "dense_vector",
    "sparse_vector",
}


class SearchProfileExecutionError(ValueError):
    """Raised when a profile cannot be executed without changing its meaning."""


class FTS5UnavailableError(RuntimeError):
    """Raised when the SQLite runtime does not provide the FTS5 extension."""


@dataclass(frozen=True, slots=True)
class QueryVector:
    """Caller-provided query vector with an explicit embedding-space identity."""

    space_id: str
    vector: Any


@dataclass(slots=True)
class _Candidate:
    subject_id: str
    subject: Mapping[str, Any]
    representations: list[Mapping[str, Any]]


@dataclass(slots=True)
class _StageRun:
    stage_id: str
    kind: str
    status: str
    backend_operation: str
    scores: dict[str, float]
    latency_ms: float
    reason: str | None = None
    examined: int = 0

    def receipt(self) -> dict[str, Any]:
        ranked = _rank_scores(self.scores)
        receipt: dict[str, Any] = {
            "stage_id": self.stage_id,
            "kind": self.kind,
            "status": self.status,
            "backend_operation": self.backend_operation,
            "examined": self.examined,
            "candidate_count": len(ranked),
            "latency_ms": round(self.latency_ms, 6),
            "returned_ids": [subject_id for subject_id, _ in ranked],
        }
        if self.reason is not None:
            receipt["reason"] = self.reason
        return receipt


def fts5_available() -> bool:
    """Return whether this process can create and query an FTS5 virtual table."""

    try:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE VIRTUAL TABLE ocg_fts_probe USING fts5(text)")
            connection.execute("INSERT INTO ocg_fts_probe(text) VALUES ('probe')")
            connection.execute(
                "SELECT rowid FROM ocg_fts_probe WHERE ocg_fts_probe MATCH 'probe'"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    return True


def require_fts5() -> None:
    """Fail with an actionable error if the active SQLite lacks FTS5."""

    try:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE VIRTUAL TABLE ocg_fts_probe USING fts5(text)")
            connection.execute("INSERT INTO ocg_fts_probe(text) VALUES ('probe')")
            row = connection.execute(
                "SELECT rowid FROM ocg_fts_probe WHERE ocg_fts_probe MATCH 'probe'"
            ).fetchone()
            if row is None:
                raise sqlite3.OperationalError("FTS5 probe query returned no row")
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise FTS5UnavailableError(
            "SQLite FTS5 is unavailable in the active Python runtime; "
            "the sqlite_fts5 OCG search backend cannot execute"
        ) from exc


def execute_search_profile(
    document: Mapping[str, Any],
    *,
    query_text: str,
    profile_id: str | None = None,
    backend: str = "reference",
    filters: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    query_vectors: Mapping[str, QueryVector | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute one portable OCG search profile and return results plus a receipt.

    ``query_vectors`` is keyed by stage ID or embedding ``space_id``.  Each
    value must be a :class:`QueryVector` or an object with ``space_id`` and
    ``vector``.  Bare vectors are rejected because their comparison space is
    ambiguous.  Missing vectors cause the corresponding vector stage to be
    reported as skipped; they are never synthesized from ``query_text``.
    """

    normalized_backend = {
        "python": "reference",
        "python_reference": "reference",
        "sqlite": "sqlite_fts5",
        "fts5": "sqlite_fts5",
    }.get(backend, backend)
    if normalized_backend not in {"reference", "sqlite_fts5"}:
        raise SearchProfileExecutionError(
            f"unknown search backend {backend!r}; expected 'reference' or 'sqlite_fts5'"
        )
    if normalized_backend == "sqlite_fts5":
        require_fts5()

    profile = _select_profile(document, profile_id)
    representations = _representation_index(document)
    record_index = _record_index(document)
    candidates = _build_candidates(document, record_index)
    request_filters = _normalize_filters(filters)
    hard_gates = _as_filter_list(profile.get("hard_gates")) + request_filters
    gated_candidates = {
        subject_id: candidate
        for subject_id, candidate in candidates.items()
        if _matches_all_filters(candidate, hard_gates)
    }

    started = perf_counter_ns()
    stage_runs = _execute_stages(
        profile,
        representations,
        gated_candidates,
        query_text=query_text,
        query_vectors=query_vectors or {},
        backend=normalized_backend,
    )
    fused_scores, per_subject_stage_scores = _fuse(profile, stage_runs)
    ranked = _rank_scores(fused_scores)
    ranked = _diversify(ranked, gated_candidates, profile.get("output", {}))
    output_limit = _positive_int(profile.get("output", {}).get("limit"), "output.limit")
    ranked = ranked[:output_limit]

    results = []
    include_fields = profile.get("output", {}).get("include_fields", [])
    for subject_id, score in ranked:
        candidate = gated_candidates[subject_id]
        projected = _project_subject(candidate.subject, include_fields)
        projected.update(
            {
                "id": subject_id,
                "search_score": round(score, 12),
                "stage_scores": {
                    key: round(value, 12)
                    for key, value in sorted(per_subject_stage_scores[subject_id].items())
                },
                "candidate_only": True,
                "serves_truth": False,
                "planning_eligibility": "not_evaluated",
                "execution_authorized": False,
            }
        )
        results.append(projected)

    total_latency_ms = (perf_counter_ns() - started) / 1_000_000
    profile_digest = _digest_json(profile)
    index_snapshot = _digest_json(
        {
            collection: document.get(collection, [])
            for collection in INDEXED_COLLECTIONS
            if collection in document
        }
    )
    query_digest = _digest_json(
        {
            "query_text": query_text,
            "filters": request_filters,
            "query_vectors": _query_vectors_for_digest(query_vectors or {}),
        }
    )
    receipt = {
        "receipt_version": "ocg-search-receipt/0.1",
        "executed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "profile": {
            "id": profile["id"],
            "version": profile["version"],
            "digest": profile_digest,
        },
        "backend": _backend_identity(normalized_backend),
        "execution_scope": {
            "lexical": (
                "python-token-scan"
                if normalized_backend == "reference"
                else "sqlite-fts5-match-bm25"
            ),
            "vector_scoring": "shared-python-explicit-vector-comparison",
            "fusion": "shared-python-profile-fusion",
            "full_stack_backend_independence": False,
        },
        "index_snapshot": index_snapshot,
        "query_digest": query_digest,
        "query_vectors": _query_vector_receipts(query_vectors or {}),
        "parameters": {
            "hard_gates": profile.get("hard_gates", []),
            "request_filters": request_filters,
            "fusion": profile["fusion"],
            "output": profile["output"],
        },
        "stages": [stage_run.receipt() for stage_run in stage_runs],
        "latency_ms": round(total_latency_ms, 6),
        "latency_scope": {
            "total": (
                "cold per-query execution; sqlite includes in-memory FTS5 index construction"
                if normalized_backend == "sqlite_fts5"
                else "per-query execution without a separately materialized index"
            ),
            "stage": "individual stage timing excludes shared setup and fusion",
            "cross_backend_performance_comparable": False,
        },
        "returned_ids": [subject_id for subject_id, _ in ranked],
        "candidate_only": True,
        "eligibility_evaluated": False,
        "search_scores_authorize_execution": False,
    }
    return {
        "profile_id": profile["id"],
        "backend": normalized_backend,
        "query": query_text,
        "count": len(results),
        "results": results,
        "receipt": receipt,
        "candidate_only": True,
        "eligibility_evaluated": False,
        "search_scores_authorize_execution": False,
    }


def run_search_bakeoff(
    document: Mapping[str, Any],
    *,
    query_text: str,
    profile_id: str | None = None,
    filters: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    query_vectors: Mapping[str, QueryVector | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute both local backends and report their result/rank agreement."""

    require_fts5()
    reference = execute_search_profile(
        document,
        query_text=query_text,
        profile_id=profile_id,
        backend="reference",
        filters=filters,
        query_vectors=query_vectors,
    )
    sqlite_result = execute_search_profile(
        document,
        query_text=query_text,
        profile_id=profile_id,
        backend="sqlite_fts5",
        filters=filters,
        query_vectors=query_vectors,
    )
    agreement = compare_backend_results(reference, sqlite_result)
    return {
        "profile_id": reference["profile_id"],
        "query": query_text,
        "runs": {
            "reference": reference,
            "sqlite_fts5": sqlite_result,
        },
        "agreement": agreement,
        "candidate_only": True,
        "eligibility_evaluated": False,
        "search_scores_authorize_execution": False,
    }


def compare_backend_results(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any]:
    """Return transparent top-k set and ordering agreement metrics."""

    left_ids = list(left.get("receipt", {}).get("returned_ids", []))
    right_ids = list(right.get("receipt", {}).get("returned_ids", []))
    left_set = set(left_ids)
    right_set = set(right_ids)
    intersection = left_set & right_set
    union = left_set | right_set
    denominator = max(len(left_ids), len(right_ids), 1)
    common_displacements = [
        abs(left_ids.index(subject_id) - right_ids.index(subject_id))
        for subject_id in intersection
    ]
    prefix = 0
    for left_id, right_id in zip(left_ids, right_ids):
        if left_id != right_id:
            break
        prefix += 1
    return {
        "left_backend": left.get("backend"),
        "right_backend": right.get("backend"),
        "left_count": len(left_ids),
        "right_count": len(right_ids),
        "intersection_count": len(intersection),
        "union_count": len(union),
        "jaccard": round(len(intersection) / len(union), 12) if union else 1.0,
        "overlap_at_returned_k": round(len(intersection) / denominator, 12),
        "top1_match": bool(left_ids and right_ids and left_ids[0] == right_ids[0]),
        "exact_order_match": left_ids == right_ids,
        "common_prefix_length": prefix,
        "mean_absolute_rank_displacement": (
            round(sum(common_displacements) / len(common_displacements), 12)
            if common_displacements
            else None
        ),
        "only_left": sorted(left_set - right_set),
        "only_right": sorted(right_set - left_set),
        "candidate_only": True,
        "eligibility_evaluated": False,
    }


def _select_profile(
    document: Mapping[str, Any], profile_id: str | None
) -> Mapping[str, Any]:
    profiles = [row for row in document.get("search_profiles", []) if isinstance(row, Mapping)]
    if profile_id is None:
        if len(profiles) != 1:
            raise SearchProfileExecutionError(
                "profile_id is required when the document does not contain exactly one search profile"
            )
        profile = profiles[0]
    else:
        matches = [row for row in profiles if row.get("id") == profile_id]
        if len(matches) != 1:
            raise SearchProfileExecutionError(
                f"search profile {profile_id!r} was not found exactly once"
            )
        profile = matches[0]
    for field in ("id", "version", "stages", "fusion", "output"):
        if field not in profile:
            raise SearchProfileExecutionError(f"search profile is missing required field {field!r}")
    if not isinstance(profile["stages"], list) or not profile["stages"]:
        raise SearchProfileExecutionError("search profile stages must be a non-empty array")
    if profile.get("status") == "revoked":
        raise SearchProfileExecutionError("a revoked search profile cannot be executed")
    return profile


def _record_index(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for collection in INDEXED_COLLECTIONS:
        for row in document.get(collection, []):
            if not isinstance(row, Mapping) or not isinstance(row.get("id"), str):
                continue
            if row["id"] in records:
                raise SearchProfileExecutionError(f"duplicate record ID {row['id']!r}")
            records[row["id"]] = row
    return records


def _representation_index(
    document: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in document.get("representations", []):
        if isinstance(row, Mapping) and isinstance(row.get("id"), str):
            result[row["id"]] = row
    return result


def _build_candidates(
    document: Mapping[str, Any], record_index: Mapping[str, Mapping[str, Any]]
) -> dict[str, _Candidate]:
    candidates: dict[str, _Candidate] = {}
    for collection in SEARCHABLE_COLLECTIONS:
        for row in document.get(collection, []):
            if isinstance(row, Mapping) and isinstance(row.get("id"), str):
                candidates[row["id"]] = _Candidate(row["id"], row, [])
    for representation in document.get("representations", []):
        if not isinstance(representation, Mapping):
            continue
        subject_id = representation.get("subject_ref")
        if not isinstance(subject_id, str):
            continue
        subject = record_index.get(subject_id)
        if subject is None:
            raise SearchProfileExecutionError(
                f"representation {representation.get('id')!r} has unknown subject_ref {subject_id!r}"
            )
        candidate = candidates.setdefault(subject_id, _Candidate(subject_id, subject, []))
        candidate.representations.append(representation)
    for candidate in candidates.values():
        candidate.representations.sort(key=lambda row: str(row.get("id", "")))
    return candidates


def _execute_stages(
    profile: Mapping[str, Any],
    representation_index: Mapping[str, Mapping[str, Any]],
    candidates: Mapping[str, _Candidate],
    *,
    query_text: str,
    query_vectors: Mapping[str, QueryVector | Mapping[str, Any]],
    backend: str,
) -> list[_StageRun]:
    stages = profile["stages"]
    seen_stage_ids: set[str] = set()
    selected_by_stage: dict[str, list[Mapping[str, Any]]] = {}
    for stage in stages:
        if not isinstance(stage, Mapping) or not isinstance(stage.get("id"), str):
            raise SearchProfileExecutionError("every search stage requires a string id")
        stage_id = stage["id"]
        if stage_id in seen_stage_ids:
            raise SearchProfileExecutionError(f"duplicate search stage ID {stage_id!r}")
        seen_stage_ids.add(stage_id)
        selected_by_stage[stage_id] = _select_representations(stage, representation_index)

    _validate_profile_execution(profile, selected_by_stage)

    fts_connection: sqlite3.Connection | None = None
    if backend == "sqlite_fts5":
        fts_connection = _build_fts_index(stages, selected_by_stage)
    runs: list[_StageRun] = []
    try:
        for stage in stages:
            stage_id = stage["id"]
            kind = stage.get("kind")
            if kind not in SUPPORTED_STAGE_KINDS:
                runs.append(
                    _StageRun(
                        stage_id=stage_id,
                        kind=str(kind),
                        status="skipped",
                        backend_operation="none",
                        scores={},
                        latency_ms=0.0,
                        reason=f"stage_kind_not_supported:{kind}",
                    )
                )
                continue
            if kind == "structured_filter":
                runs.append(_run_structured_stage(stage, candidates))
            elif kind == "lexical":
                if backend == "reference":
                    runs.append(
                        _run_reference_lexical_stage(
                            stage, selected_by_stage[stage_id], candidates, query_text
                        )
                    )
                else:
                    assert fts_connection is not None
                    runs.append(
                        _run_sqlite_lexical_stage(
                            fts_connection,
                            stage,
                            selected_by_stage[stage_id],
                            candidates,
                            query_text,
                        )
                    )
            else:
                runs.append(
                    _run_vector_stage(
                        stage,
                        selected_by_stage[stage_id],
                        candidates,
                        query_vectors,
                    )
                )
    finally:
        if fts_connection is not None:
            fts_connection.close()
    return runs


def _validate_profile_execution(
    profile: Mapping[str, Any],
    selected_by_stage: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    """Reject vector comparisons/fusions whose score semantics are ambiguous."""

    stage_by_id = {
        stage.get("id"): stage
        for stage in profile["stages"]
        if isinstance(stage, Mapping) and isinstance(stage.get("id"), str)
    }
    vector_spaces: set[tuple[Any, ...]] = set()
    for stage_id, stage in stage_by_id.items():
        if stage.get("kind") not in VECTOR_STAGE_KINDS:
            continue
        signatures: set[tuple[Any, ...]] = set()
        for representation in selected_by_stage[stage_id]:
            embedding = representation.get("embedding")
            if not isinstance(embedding, Mapping):
                continue
            signature = (
                embedding.get("space_id"),
                embedding.get("dimensions"),
                embedding.get("normalization"),
                embedding.get("distance"),
            )
            signatures.add(signature)
            vector_spaces.add(signature)
        if len(signatures) > 1:
            raise SearchProfileExecutionError(
                f"vector stage {stage_id!r} selects more than one directly comparable "
                "embedding space; split the spaces into separate stages and use rank fusion "
                "or declared calibration"
            )

    fusion = profile.get("fusion")
    if not isinstance(fusion, Mapping):
        return
    if fusion.get("method") not in {"weighted_sum", "weighted_normalized_sum"}:
        return
    if len(vector_spaces) <= 1:
        return
    inputs = fusion.get("inputs", [])
    missing = [
        item.get("stage_ref")
        for item in inputs
        if isinstance(item, Mapping) and not item.get("calibration_ref")
    ]
    if missing:
        raise SearchProfileExecutionError(
            "cross-space score summation requires calibration_ref on every fusion input; "
            f"missing for {missing!r}"
        )


def _select_representations(
    stage: Mapping[str, Any],
    representation_index: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    references = stage.get("representation_refs")
    selector = stage.get("representation_selector")
    if references is not None:
        if not isinstance(references, list):
            raise SearchProfileExecutionError(
                f"stage {stage.get('id')!r} representation_refs must be an array"
            )
        selected = []
        for reference in references:
            representation = representation_index.get(reference)
            if representation is None:
                raise SearchProfileExecutionError(
                    f"stage {stage.get('id')!r} references unknown representation {reference!r}"
                )
            if _representation_is_searchable(representation):
                selected.append(representation)
        return selected
    if selector is not None:
        if not isinstance(selector, Mapping):
            raise SearchProfileExecutionError(
                f"stage {stage.get('id')!r} representation_selector must be an object"
            )
        return [
            representation
            for representation in representation_index.values()
            if _representation_is_searchable(representation)
            and _mapping_contains(representation, selector)
        ]
    if stage.get("kind") in {"structured_filter", "graph", "custom"}:
        return []
    raise SearchProfileExecutionError(
        f"stage {stage.get('id')!r} requires representation_refs or representation_selector"
    )


def _representation_is_searchable(representation: Mapping[str, Any]) -> bool:
    return representation.get("lifecycle") not in NON_SEARCHABLE_LIFECYCLES


def _mapping_contains(value: Mapping[str, Any], selector: Mapping[str, Any]) -> bool:
    for key, expected in selector.items():
        actual = value.get(key)
        if isinstance(expected, Mapping):
            if not isinstance(actual, Mapping) or not _mapping_contains(actual, expected):
                return False
        elif actual != expected:
            return False
    return True


def _run_structured_stage(
    stage: Mapping[str, Any], candidates: Mapping[str, _Candidate]
) -> _StageRun:
    started = perf_counter_ns()
    stage_filters = _as_filter_list(stage.get("filters"))
    scores = {
        subject_id: 1.0
        for subject_id, candidate in candidates.items()
        if _matches_all_filters(candidate, stage_filters)
    }
    scores = _limit_scores(scores, _positive_int(stage.get("candidate_limit"), "candidate_limit"))
    return _StageRun(
        stage_id=stage["id"],
        kind="structured_filter",
        status="executed",
        backend_operation="deterministic-structured-filter",
        scores=scores,
        latency_ms=(perf_counter_ns() - started) / 1_000_000,
        examined=len(candidates),
    )


def _run_reference_lexical_stage(
    stage: Mapping[str, Any],
    representations: Sequence[Mapping[str, Any]],
    candidates: Mapping[str, _Candidate],
    query_text: str,
) -> _StageRun:
    started = perf_counter_ns()
    query_terms = Counter(_tokenize(query_text))
    if not query_terms:
        return _StageRun(
            stage_id=stage["id"],
            kind="lexical",
            status="skipped",
            backend_operation="python-token-scan",
            scores={},
            latency_ms=(perf_counter_ns() - started) / 1_000_000,
            reason="empty_lexical_query",
        )
    stage_filters = _as_filter_list(stage.get("filters"))
    scores: dict[str, float] = {}
    examined = 0
    for representation in representations:
        if representation.get("encoding") != "lexical":
            raise SearchProfileExecutionError(
                f"lexical stage {stage['id']!r} selected non-lexical representation "
                f"{representation.get('id')!r}"
            )
        subject_id = representation.get("subject_ref")
        candidate = candidates.get(subject_id)
        if candidate is None or not _matches_all_filters(candidate, stage_filters):
            continue
        examined += 1
        document_terms = Counter(_tokenize(str(representation.get("text", ""))))
        matched = sum(min(count, document_terms[term]) for term, count in query_terms.items())
        if matched == 0:
            continue
        score = matched / sum(query_terms.values())
        scores[subject_id] = max(scores.get(subject_id, float("-inf")), score)
    scores = _limit_scores(scores, _positive_int(stage.get("candidate_limit"), "candidate_limit"))
    return _StageRun(
        stage_id=stage["id"],
        kind="lexical",
        status="executed",
        backend_operation="python-token-scan",
        scores=scores,
        latency_ms=(perf_counter_ns() - started) / 1_000_000,
        examined=examined,
    )


def _build_fts_index(
    stages: Sequence[Mapping[str, Any]],
    selected_by_stage: Mapping[str, Sequence[Mapping[str, Any]]],
) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE ocg_search USING fts5(
              stage_id UNINDEXED,
              representation_id UNINDEXED,
              subject_id UNINDEXED,
              text,
              tokenize = 'unicode61'
            )
            """
        )
        rows = []
        for stage in stages:
            if stage.get("kind") != "lexical":
                continue
            for representation in selected_by_stage[stage["id"]]:
                if representation.get("encoding") != "lexical":
                    raise SearchProfileExecutionError(
                        f"lexical stage {stage['id']!r} selected non-lexical representation "
                        f"{representation.get('id')!r}"
                    )
                rows.append(
                    (
                        stage["id"],
                        representation.get("id"),
                        representation.get("subject_ref"),
                        str(representation.get("text", "")),
                    )
                )
        connection.executemany(
            "INSERT INTO ocg_search(stage_id, representation_id, subject_id, text) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
    except Exception:
        connection.close()
        raise
    return connection


def _run_sqlite_lexical_stage(
    connection: sqlite3.Connection,
    stage: Mapping[str, Any],
    representations: Sequence[Mapping[str, Any]],
    candidates: Mapping[str, _Candidate],
    query_text: str,
) -> _StageRun:
    started = perf_counter_ns()
    tokens = _tokenize(query_text)
    if not tokens:
        return _StageRun(
            stage_id=stage["id"],
            kind="lexical",
            status="skipped",
            backend_operation="sqlite-fts5-match-bm25",
            scores={},
            latency_ms=(perf_counter_ns() - started) / 1_000_000,
            reason="empty_lexical_query",
        )
    query = " OR ".join(f'"{token}"' for token in sorted(set(tokens)))
    rows = connection.execute(
        """
        SELECT representation_id, subject_id, bm25(ocg_search) AS lexical_rank
          FROM ocg_search
         WHERE ocg_search MATCH ? AND stage_id = ?
         ORDER BY lexical_rank ASC, subject_id ASC, representation_id ASC
        """,
        (query, stage["id"]),
    ).fetchall()
    selected_ids = {str(row.get("id")) for row in representations}
    stage_filters = _as_filter_list(stage.get("filters"))
    scores: dict[str, float] = {}
    examined = 0
    for representation_id, subject_id, raw_rank in rows:
        if representation_id not in selected_ids:
            continue
        candidate = candidates.get(subject_id)
        if candidate is None or not _matches_all_filters(candidate, stage_filters):
            continue
        examined += 1
        score = -float(raw_rank)
        scores[subject_id] = max(scores.get(subject_id, float("-inf")), score)
    scores = _limit_scores(scores, _positive_int(stage.get("candidate_limit"), "candidate_limit"))
    return _StageRun(
        stage_id=stage["id"],
        kind="lexical",
        status="executed",
        backend_operation="sqlite-fts5-match-bm25",
        scores=scores,
        latency_ms=(perf_counter_ns() - started) / 1_000_000,
        examined=examined,
    )


def _run_vector_stage(
    stage: Mapping[str, Any],
    representations: Sequence[Mapping[str, Any]],
    candidates: Mapping[str, _Candidate],
    query_vectors: Mapping[str, QueryVector | Mapping[str, Any]],
) -> _StageRun:
    started = perf_counter_ns()
    kind = str(stage["kind"])
    stage_filters = _as_filter_list(stage.get("filters"))
    scores: dict[str, float] = {}
    examined = 0
    supplied_vector_seen = False
    inline_vector_seen = False
    for representation in representations:
        if representation.get("encoding") != kind:
            raise SearchProfileExecutionError(
                f"{kind} stage {stage['id']!r} selected {representation.get('encoding')!r} "
                f"representation {representation.get('id')!r}"
            )
        embedding = representation.get("embedding")
        if not isinstance(embedding, Mapping):
            raise SearchProfileExecutionError(
                f"vector representation {representation.get('id')!r} is missing embedding metadata"
            )
        document_vector = embedding.get("vector")
        if document_vector is None:
            continue
        inline_vector_seen = True
        query_vector = _query_vector_for(stage, embedding, query_vectors)
        if query_vector is None:
            continue
        supplied_vector_seen = True
        subject_id = representation.get("subject_ref")
        candidate = candidates.get(subject_id)
        if candidate is None or not _matches_all_filters(candidate, stage_filters):
            continue
        score = _vector_similarity(query_vector.vector, document_vector, embedding, kind)
        examined += 1
        scores[subject_id] = max(scores.get(subject_id, float("-inf")), score)
    if not query_vectors:
        reason = "query_vector_not_provided"
        status = "skipped"
    elif not inline_vector_seen:
        reason = "inline_document_vectors_not_available"
        status = "skipped"
    elif not supplied_vector_seen:
        reason = "no_query_vector_for_selected_embedding_space"
        status = "skipped"
    else:
        reason = None
        status = "executed"
    scores = _limit_scores(scores, _positive_int(stage.get("candidate_limit"), "candidate_limit"))
    return _StageRun(
        stage_id=stage["id"],
        kind=kind,
        status=status,
        backend_operation="python-explicit-vector-comparison",
        scores=scores,
        latency_ms=(perf_counter_ns() - started) / 1_000_000,
        reason=reason,
        examined=examined,
    )


def _query_vector_for(
    stage: Mapping[str, Any],
    embedding: Mapping[str, Any],
    query_vectors: Mapping[str, QueryVector | Mapping[str, Any]],
) -> QueryVector | None:
    stage_id = str(stage["id"])
    space_id = embedding.get("space_id")
    raw = query_vectors.get(stage_id)
    if raw is None and isinstance(space_id, str):
        raw = query_vectors.get(space_id)
    if raw is None:
        return None
    if isinstance(raw, QueryVector):
        query_vector = raw
    elif isinstance(raw, Mapping) and "space_id" in raw and "vector" in raw:
        query_vector = QueryVector(space_id=str(raw["space_id"]), vector=raw["vector"])
    else:
        raise SearchProfileExecutionError(
            f"query vector for stage {stage_id!r} must include explicit space_id and vector"
        )
    if query_vector.space_id != space_id:
        raise SearchProfileExecutionError(
            f"query vector space {query_vector.space_id!r} does not match representation "
            f"space {space_id!r} for stage {stage_id!r}"
        )
    return query_vector


def _vector_similarity(
    query: Any,
    document: Any,
    embedding: Mapping[str, Any],
    kind: str,
) -> float:
    dimensions = _positive_int(embedding.get("dimensions"), "embedding.dimensions")
    if kind == "dense_vector":
        left = _dense_vector(query, dimensions, "query vector")
        right = _dense_vector(document, dimensions, "document vector")
    elif kind == "sparse_vector":
        left = _sparse_vector(query, dimensions, "query vector")
        right = _sparse_vector(document, dimensions, "document vector")
    else:
        raise SearchProfileExecutionError(f"unsupported vector stage kind {kind!r}")
    distance = embedding.get("distance")
    if distance == "cosine":
        denominator = _norm(left) * _norm(right)
        return _dot(left, right) / denominator if denominator else 0.0
    if distance == "dot":
        return _dot(left, right)
    if distance == "l2":
        return -math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))
    if distance == "l1":
        return -sum(abs(a - b) for a, b in zip(left, right))
    raise SearchProfileExecutionError(
        f"local vector executor does not support distance {distance!r}"
    )


def _dense_vector(value: Any, dimensions: int, label: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise SearchProfileExecutionError(f"{label} must be a numeric array")
    if len(value) != dimensions:
        raise SearchProfileExecutionError(
            f"{label} has {len(value)} dimensions; expected {dimensions}"
        )
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise SearchProfileExecutionError(f"{label} contains a non-finite numeric value")
        result.append(float(item))
    return result


def _sparse_vector(value: Any, dimensions: int, label: str) -> list[float]:
    if not isinstance(value, Mapping):
        raise SearchProfileExecutionError(
            f"{label} must contain parallel indices and values arrays"
        )
    indices = value.get("indices")
    values = value.get("values")
    if not isinstance(indices, Sequence) or not isinstance(values, Sequence):
        raise SearchProfileExecutionError(
            f"{label} must contain parallel indices and values arrays"
        )
    if len(indices) != len(values):
        raise SearchProfileExecutionError(f"{label} indices and values lengths differ")
    dense = [0.0] * dimensions
    seen: set[int] = set()
    for index, item in zip(indices, values):
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < dimensions:
            raise SearchProfileExecutionError(f"{label} has out-of-range index {index!r}")
        if index in seen:
            raise SearchProfileExecutionError(f"{label} repeats sparse index {index}")
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise SearchProfileExecutionError(f"{label} contains a non-finite numeric value")
        seen.add(index)
        dense[index] = float(item)
    return dense


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _norm(vector: Sequence[float]) -> float:
    return math.sqrt(_dot(vector, vector))


def _fuse(
    profile: Mapping[str, Any], stage_runs: Sequence[_StageRun]
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    stage_by_id = {stage.stage_id: stage for stage in stage_runs}
    fusion = profile.get("fusion")
    if not isinstance(fusion, Mapping):
        raise SearchProfileExecutionError("search profile fusion must be an object")
    method = fusion.get("method")
    inputs = fusion.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise SearchProfileExecutionError("search profile fusion.inputs must be non-empty")
    per_subject: dict[str, dict[str, float]] = defaultdict(dict)
    fused: dict[str, float] = {}
    if method == "rrf":
        rrf_k = fusion.get("parameters", {}).get("rrf_k", 60)
        if isinstance(rrf_k, bool) or not isinstance(rrf_k, (int, float)) or rrf_k < 0:
            raise SearchProfileExecutionError("fusion.parameters.rrf_k must be non-negative")
        for item in inputs:
            stage, weight = _fusion_input(item, stage_by_id)
            for rank, (subject_id, raw_score) in enumerate(_rank_scores(stage.scores), start=1):
                per_subject[subject_id][stage.stage_id] = raw_score
                fused[subject_id] = fused.get(subject_id, 0.0) + weight / (float(rrf_k) + rank)
        return fused, per_subject
    if method not in {"weighted_sum", "weighted_normalized_sum", "minimum", "maximum"}:
        raise SearchProfileExecutionError(
            f"fusion method {method!r} is not executable by the local bakeoff"
        )
    contributions: dict[str, list[float]] = defaultdict(list)
    for item in inputs:
        stage, weight = _fusion_input(item, stage_by_id)
        stage_scores = stage.scores
        if method == "weighted_normalized_sum":
            stage_scores = _min_max_normalize(stage_scores)
        for subject_id, raw_score in stage.scores.items():
            per_subject[subject_id][stage.stage_id] = raw_score
        for subject_id, score in stage_scores.items():
            contributions[subject_id].append(weight * score)
    for subject_id, values in contributions.items():
        if method in {"weighted_sum", "weighted_normalized_sum"}:
            fused[subject_id] = sum(values)
        elif method == "minimum":
            fused[subject_id] = min(values)
        else:
            fused[subject_id] = max(values)
    return fused, per_subject


def _fusion_input(
    item: Any, stage_by_id: Mapping[str, _StageRun]
) -> tuple[_StageRun, float]:
    if not isinstance(item, Mapping):
        raise SearchProfileExecutionError("every fusion input must be an object")
    stage_ref = item.get("stage_ref")
    stage = stage_by_id.get(stage_ref)
    if stage is None:
        raise SearchProfileExecutionError(f"fusion references unknown stage {stage_ref!r}")
    weight = item.get("weight")
    if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0:
        raise SearchProfileExecutionError(
            f"fusion weight for stage {stage_ref!r} must be a non-negative number"
        )
    return stage, float(weight)


def _min_max_normalize(scores: Mapping[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    low = min(scores.values())
    high = max(scores.values())
    if low == high:
        return {subject_id: 1.0 for subject_id in scores}
    return {subject_id: (score - low) / (high - low) for subject_id, score in scores.items()}


def _rank_scores(scores: Mapping[str, float]) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _limit_scores(scores: Mapping[str, float], limit: int) -> dict[str, float]:
    return dict(_rank_scores(scores)[:limit])


def _diversify(
    ranked: Sequence[tuple[str, float]],
    candidates: Mapping[str, _Candidate],
    output: Mapping[str, Any],
) -> list[tuple[str, float]]:
    fields = output.get("diversify_by", [])
    if not isinstance(fields, list) or not fields:
        return list(ranked)
    selected: list[tuple[str, float]] = []
    deferred: list[tuple[str, float]] = []
    seen: set[str] = set()
    for subject_id, score in ranked:
        candidate = candidates[subject_id]
        values = []
        for field in fields:
            field_values = _field_values(candidate, str(field))
            values.append(field_values[0] if field_values else None)
        if all(value is None for value in values):
            key = f"missing:{subject_id}"
        else:
            key = json.dumps(values, sort_keys=True, default=str)
        if key in seen:
            deferred.append((subject_id, score))
        else:
            seen.add(key)
            selected.append((subject_id, score))
    return selected + deferred


def _project_subject(subject: Mapping[str, Any], include_fields: Any) -> dict[str, Any]:
    if not isinstance(include_fields, list):
        return {}
    return {
        field: subject[field]
        for field in include_fields
        if isinstance(field, str) and field != "id" and field in subject
    }


def _normalize_filters(
    filters: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    if filters is None:
        return []
    if isinstance(filters, Mapping):
        if {"field", "operator", "value"}.issubset(filters):
            return [filters]
        return [
            {"field": str(field), "operator": "eq", "value": value}
            for field, value in sorted(filters.items())
        ]
    if isinstance(filters, Sequence) and not isinstance(filters, (str, bytes, bytearray)):
        return _as_filter_list(filters)
    raise SearchProfileExecutionError("filters must be a mapping or an array of filter objects")


def _as_filter_list(value: Any) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SearchProfileExecutionError("search filters must be an array")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise SearchProfileExecutionError("every search filter must be an object")
        if not {"field", "operator", "value"}.issubset(item):
            raise SearchProfileExecutionError(
                "every search filter requires field, operator, and value"
            )
        result.append(item)
    return result


def _matches_all_filters(
    candidate: _Candidate, filters: Sequence[Mapping[str, Any]]
) -> bool:
    return all(_matches_filter(candidate, search_filter) for search_filter in filters)


def _matches_filter(candidate: _Candidate, search_filter: Mapping[str, Any]) -> bool:
    field = str(search_filter["field"])
    operator = search_filter["operator"]
    expected = search_filter["value"]
    values = _field_values(candidate, field)
    if operator == "exists":
        return bool(values) if bool(expected) else not values
    if operator == "eq":
        return any(value == expected for value in values)
    if operator == "ne":
        return all(value != expected for value in values)
    if operator in {"in", "not_in"}:
        expected_values = expected if isinstance(expected, list) else [expected]
        matched = any(
            any(item in expected_values for item in value)
            if isinstance(value, list)
            else value in expected_values
            for value in values
        )
        return not matched if operator == "not_in" else matched
    if operator == "contains":
        return any(
            expected in value
            if isinstance(value, (str, list, tuple, set, dict))
            else False
            for value in values
        )
    if operator in {"gt", "gte", "lt", "lte"}:
        comparisons = {
            "gt": lambda actual: actual > expected,
            "gte": lambda actual: actual >= expected,
            "lt": lambda actual: actual < expected,
            "lte": lambda actual: actual <= expected,
        }
        for value in values:
            try:
                if comparisons[operator](value):
                    return True
            except TypeError:
                continue
        return False
    raise SearchProfileExecutionError(f"unsupported search filter operator {operator!r}")


def _field_values(candidate: _Candidate, field: str) -> list[Any]:
    if field.startswith("subject."):
        value = _path_value(candidate.subject, field.removeprefix("subject."))
        return [] if value is _MISSING else [value]
    if field.startswith("representation."):
        path = field.removeprefix("representation.")
        return [
            value
            for representation in candidate.representations
            if (value := _path_value(representation, path)) is not _MISSING
        ]
    subject_value = _path_value(candidate.subject, field)
    if subject_value is not _MISSING:
        return [subject_value]
    return [
        value
        for representation in candidate.representations
        if (value := _path_value(representation, field)) is not _MISSING
    ]


_MISSING = object()


def _path_value(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _tokenize(value: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(value.lower()):
        tokens.append(raw)
        if "_" in raw or "-" in raw:
            tokens.extend(part for part in re.split(r"[_-]+", raw) if part)
    return tokens


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SearchProfileExecutionError(f"{field} must be a positive integer")
    return value


def _digest_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _query_vectors_for_digest(
    query_vectors: Mapping[str, QueryVector | Mapping[str, Any]],
) -> dict[str, Any]:
    result = {}
    for key, value in sorted(query_vectors.items()):
        if isinstance(value, QueryVector):
            result[key] = {"space_id": value.space_id, "vector": value.vector}
        else:
            result[key] = dict(value)
    return result


def _query_vector_receipts(
    query_vectors: Mapping[str, QueryVector | Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    normalized = _query_vectors_for_digest(query_vectors)
    return {
        key: {
            "space_id": value.get("space_id"),
            "vector_digest": _digest_json(value.get("vector")),
        }
        for key, value in sorted(normalized.items())
    }


def _backend_identity(backend: str) -> dict[str, str]:
    if backend == "reference":
        return {
            "id": "python-reference-scan",
            "version": platform.python_version(),
        }
    return {
        "id": "sqlite-fts5",
        "version": sqlite3.sqlite_version,
    }
