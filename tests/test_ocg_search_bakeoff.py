from __future__ import annotations

from copy import deepcopy
import json
import sqlite3
import unittest
from unittest.mock import patch

from aidevobserver_fabric import ocg_search_bakeoff as bakeoff


def embedding(space_id: str, vector, *, encoding: str):
    dimensions = len(vector) if isinstance(vector, list) else 4
    return {
        "space_id": space_id,
        "model": {"id": f"model:{space_id}", "revision": "1", "task": "symmetric"},
        "dimensions": dimensions,
        "dtype": "float32" if encoding == "dense_vector" else "sparse_float32",
        "normalization": "none",
        "distance": "cosine",
        "generation": {"generated_at": "2026-07-11T00:00:00Z", "generator": "fixture"},
        "vector": vector,
    }


def representation(identifier: str, subject: str, encoding: str, payload):
    row = {
        "id": identifier,
        "subject_ref": subject,
        "view_kind": "view:intent",
        "source_digest": "sha256:" + ("1" * 64),
        "encoding": encoding,
        "lifecycle": "active",
    }
    if encoding == "lexical":
        row["text"] = payload
    else:
        space = "space:dense" if encoding == "dense_vector" else "space:sparse"
        row["projection_recipe"] = {
            "id": f"projection:{identifier}",
            "digest": "sha256:" + ("2" * 64),
        }
        row["embedding"] = embedding(space, payload, encoding=encoding)
    return row


def fixture_document():
    subjects = [
        {
            "id": "cap:normalize",
            "kind": "capability",
            "label": "Normalize customer email",
            "tags": ["customer", "normalization"],
            "lifecycle": "active",
        },
        {
            "id": "cap:adapt",
            "kind": "capability",
            "label": "Adapt customer export",
            "tags": ["customer", "adapter"],
            "lifecycle": "active",
        },
        {
            "id": "cap:emit",
            "kind": "capability",
            "label": "Emit JSON",
            "tags": ["serialization"],
            "lifecycle": "active",
        },
        {
            "id": "cap:revoked-copy",
            "kind": "capability",
            "label": "Revoked customer normalizer",
            "tags": ["customer", "normalization"],
            "lifecycle": "revoked",
        },
    ]
    lexical = [
        representation(
            "rep:normalize:lexical",
            "cap:normalize",
            "lexical",
            "normalize customer email identity record",
        ),
        representation(
            "rep:adapt:lexical",
            "cap:adapt",
            "lexical",
            "adapt customer record fields for export",
        ),
        representation(
            "rep:emit:lexical",
            "cap:emit",
            "lexical",
            "serialize export record as deterministic json",
        ),
        representation(
            "rep:revoked:lexical",
            "cap:revoked-copy",
            "lexical",
            "normalize customer email identity record",
        ),
    ]
    dense = [
        representation("rep:normalize:dense", "cap:normalize", "dense_vector", [1.0, 0.0]),
        representation("rep:adapt:dense", "cap:adapt", "dense_vector", [0.7, 0.7]),
        representation("rep:emit:dense", "cap:emit", "dense_vector", [0.0, 1.0]),
    ]
    sparse = [
        representation(
            "rep:normalize:sparse",
            "cap:normalize",
            "sparse_vector",
            {"indices": [0], "values": [1.0]},
        ),
        representation(
            "rep:adapt:sparse",
            "cap:adapt",
            "sparse_vector",
            {"indices": [0, 1], "values": [0.7, 0.7]},
        ),
        representation(
            "rep:emit:sparse",
            "cap:emit",
            "sparse_vector",
            {"indices": [1], "values": [1.0]},
        ),
    ]
    profile = {
        "id": "profile:portable-hybrid",
        "version": "0.1.0",
        "created_at": "2026-07-11T00:00:00Z",
        "status": "candidate",
        "hard_gates": [
            {"field": "lifecycle", "operator": "not_in", "value": ["revoked", "rejected"]}
        ],
        "stages": [
            {
                "id": "lexical",
                "kind": "lexical",
                "representation_refs": [row["id"] for row in lexical],
                "query_view": "view:intent",
                "candidate_limit": 10,
            },
            {
                "id": "customer-facet",
                "kind": "structured_filter",
                "filters": [{"field": "tags", "operator": "contains", "value": "customer"}],
                "candidate_limit": 10,
            },
            {
                "id": "dense",
                "kind": "dense_vector",
                "representation_refs": [row["id"] for row in dense],
                "query_view": "view:intent",
                "candidate_limit": 10,
            },
            {
                "id": "sparse",
                "kind": "sparse_vector",
                "representation_refs": [row["id"] for row in sparse],
                "query_view": "view:intent",
                "candidate_limit": 10,
            },
        ],
        "fusion": {
            "method": "rrf",
            "inputs": [
                {"stage_ref": "lexical", "weight": 1.0},
                {"stage_ref": "customer-facet", "weight": 0.4},
                {"stage_ref": "dense", "weight": 1.0},
                {"stage_ref": "sparse", "weight": 0.8},
            ],
            "parameters": {"rrf_k": 10, "weights_are_query_preferences_not_truth": True},
        },
        "output": {"limit": 3, "include_fields": ["id", "label", "lifecycle", "tags"]},
    }
    return {
        "ocg_version": "0.1.0-draft",
        "profiles": ["core", "retrieval"],
        "nodes": subjects,
        "actions": [],
        "relations": [],
        "representations": lexical + dense + sparse,
        "search_profiles": [profile],
    }


QUERY_VECTORS = {
    "dense": {"space_id": "space:dense", "vector": [1.0, 0.0]},
    "sparse": {
        "space_id": "space:sparse",
        "vector": {"indices": [0], "values": [1.0]},
    },
}


class OCGSearchBakeoffTests(unittest.TestCase):
    def test_bakeoff_executes_reference_and_real_fts5_backends(self):
        if not bakeoff.fts5_available():
            self.skipTest("active SQLite does not provide FTS5")
        result = bakeoff.run_search_bakeoff(
            fixture_document(),
            query_text="normalize customer email",
            query_vectors=QUERY_VECTORS,
        )
        reference = result["runs"]["reference"]
        sqlite_result = result["runs"]["sqlite_fts5"]
        self.assertEqual(reference["results"][0]["id"], "cap:normalize")
        self.assertEqual(sqlite_result["results"][0]["id"], "cap:normalize")
        self.assertEqual(reference["receipt"]["backend"]["id"], "python-reference-scan")
        self.assertEqual(sqlite_result["receipt"]["backend"]["id"], "sqlite-fts5")
        sqlite_lexical = next(
            row for row in sqlite_result["receipt"]["stages"] if row["stage_id"] == "lexical"
        )
        self.assertEqual(sqlite_lexical["backend_operation"], "sqlite-fts5-match-bm25")
        self.assertEqual(sqlite_lexical["status"], "executed")
        self.assertEqual(
            reference["receipt"]["profile"], sqlite_result["receipt"]["profile"]
        )
        self.assertEqual(
            reference["receipt"]["index_snapshot"],
            sqlite_result["receipt"]["index_snapshot"],
        )
        self.assertEqual(
            reference["receipt"]["query_digest"], sqlite_result["receipt"]["query_digest"]
        )
        self.assertFalse(
            sqlite_result["receipt"]["execution_scope"]["full_stack_backend_independence"]
        )
        self.assertFalse(
            sqlite_result["receipt"]["latency_scope"]["cross_backend_performance_comparable"]
        )
        self.assertEqual(set(reference["receipt"]["query_vectors"]), {"dense", "sparse"})
        self.assertTrue(
            all(
                row["vector_digest"].startswith("sha256:")
                for row in reference["receipt"]["query_vectors"].values()
            )
        )
        self.assertTrue(result["agreement"]["top1_match"])
        self.assertGreaterEqual(result["agreement"]["jaccard"], 2 / 3)
        self.assertGreaterEqual(reference["receipt"]["latency_ms"], 0)
        self.assertGreaterEqual(sqlite_result["receipt"]["latency_ms"], 0)
        json.dumps(result, allow_nan=False)

    def test_results_and_receipts_never_promote_search_to_eligibility(self):
        result = bakeoff.execute_search_profile(
            fixture_document(),
            query_text="normalize customer email",
            backend="reference",
            query_vectors=QUERY_VECTORS,
        )
        self.assertTrue(result["candidate_only"])
        self.assertFalse(result["eligibility_evaluated"])
        self.assertFalse(result["search_scores_authorize_execution"])
        self.assertFalse(result["receipt"]["search_scores_authorize_execution"])
        for hit in result["results"]:
            self.assertTrue(hit["candidate_only"])
            self.assertFalse(hit["serves_truth"])
            self.assertEqual(hit["planning_eligibility"], "not_evaluated")
            self.assertFalse(hit["execution_authorized"])
        self.assertNotIn("cap:revoked-copy", result["receipt"]["returned_ids"])

    def test_revoked_representations_are_excluded_before_every_stage(self):
        document = fixture_document()
        for row in document["representations"]:
            if row["subject_ref"] == "cap:normalize":
                row["lifecycle"] = "revoked"
        result = bakeoff.execute_search_profile(
            document,
            query_text="normalize customer email",
            backend="reference",
            query_vectors=QUERY_VECTORS,
        )
        for stage in result["receipt"]["stages"]:
            if stage["kind"] in {"lexical", "dense_vector", "sparse_vector"}:
                self.assertNotIn("cap:normalize", stage["returned_ids"])

    def test_vector_stages_skip_instead_of_fabricating_embeddings(self):
        result = bakeoff.execute_search_profile(
            fixture_document(),
            query_text="normalize customer email",
            backend="reference",
        )
        stages = {row["stage_id"]: row for row in result["receipt"]["stages"]}
        self.assertEqual(stages["lexical"]["status"], "executed")
        self.assertEqual(stages["dense"]["status"], "skipped")
        self.assertEqual(stages["dense"]["reason"], "query_vector_not_provided")
        self.assertEqual(stages["sparse"]["status"], "skipped")
        self.assertEqual(result["results"][0]["id"], "cap:normalize")

    def test_cross_space_vector_is_rejected(self):
        bad_vectors = deepcopy(QUERY_VECTORS)
        bad_vectors["dense"]["space_id"] = "space:unrelated"
        with self.assertRaisesRegex(
            bakeoff.SearchProfileExecutionError, "does not match representation space"
        ):
            bakeoff.execute_search_profile(
                fixture_document(),
                query_text="normalize customer email",
                query_vectors=bad_vectors,
            )

    def test_request_structured_filter_is_applied_by_both_backends(self):
        result = bakeoff.run_search_bakeoff(
            fixture_document(),
            query_text="customer export",
            filters={"id": "cap:adapt"},
            query_vectors=QUERY_VECTORS,
        )
        self.assertEqual(
            result["runs"]["reference"]["receipt"]["returned_ids"], ["cap:adapt"]
        )
        self.assertEqual(
            result["runs"]["sqlite_fts5"]["receipt"]["returned_ids"], ["cap:adapt"]
        )
        self.assertEqual(result["agreement"]["jaccard"], 1.0)

    def test_bare_query_vector_is_rejected_as_ambiguous(self):
        with self.assertRaisesRegex(
            bakeoff.SearchProfileExecutionError, "must include explicit space_id"
        ):
            bakeoff.execute_search_profile(
                fixture_document(),
                query_text="normalize",
                query_vectors={"dense": [1.0, 0.0]},
            )

    def test_one_vector_stage_cannot_mix_embedding_spaces(self):
        document = fixture_document()
        representation = next(
            row for row in document["representations"] if row["id"] == "rep:adapt:dense"
        )
        representation["embedding"]["space_id"] = "space:dense-other"
        with self.assertRaisesRegex(
            bakeoff.SearchProfileExecutionError, "more than one directly comparable embedding space"
        ):
            bakeoff.execute_search_profile(
                document,
                query_text="customer",
                query_vectors=QUERY_VECTORS,
            )

    def test_cross_space_score_sum_requires_calibration(self):
        document = fixture_document()
        document["search_profiles"][0]["fusion"]["method"] = "weighted_normalized_sum"
        with self.assertRaisesRegex(
            bakeoff.SearchProfileExecutionError, "requires calibration_ref"
        ):
            bakeoff.execute_search_profile(
                document,
                query_text="customer",
                query_vectors=QUERY_VECTORS,
            )

    def test_fts5_unavailable_failure_is_explicit(self):
        with patch.object(
            bakeoff.sqlite3,
            "connect",
            side_effect=sqlite3.OperationalError("no such module: fts5"),
        ):
            with self.assertRaisesRegex(
                bakeoff.FTS5UnavailableError, "SQLite FTS5 is unavailable"
            ):
                bakeoff.require_fts5()


if __name__ == "__main__":
    unittest.main()
