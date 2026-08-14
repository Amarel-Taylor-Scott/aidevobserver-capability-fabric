from __future__ import annotations

from base64 import b64decode
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from aidevobserver_fabric.ocg_compatibility import run_held_out_benchmark
from aidevobserver_fabric.ocg_conformance import validate_document
from aidevobserver_fabric.ocg_interop import (
    build_interoperability_retrieval_graph,
    import_interoperability_fixtures,
    interoperability_compatibility_cases,
    run_interoperability_bakeoff,
    run_portable_search_bakeoff,
    validate_native_fixtures,
    write_bakeoff_artifacts,
)
from aidevobserver_fabric.ocg_search_bakeoff import fts5_available


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPO_ROOT / "spec/open-capability-graph/v0.1"
FIXTURES = SPEC_ROOT / "interoperability/fixtures"
SCHEMA_PATH = SPEC_ROOT / "schemas/open-capability-graph.schema.json"


class OCGInteropBakeoffTests(unittest.TestCase):
    def test_five_native_formats_import_as_candidate_only_graphs(self) -> None:
        imports = import_interoperability_fixtures(FIXTURES)
        self.assertEqual(
            [row.source_format for row in imports],
            ["mcp-tools", "openapi", "cwl", "wit", "agent-spec"],
        )
        self.assertEqual(sum(len(row.document["actions"]) for row in imports), 6)
        for imported in imports:
            self.assertEqual(imported.planning_eligibility, "unknown")
            self.assertEqual(imported.document["status"], "candidate")
            serialized = json.dumps(imported.document, sort_keys=True)
            self.assertNotIn(str(REPO_ROOT), serialized)
            self.assertIn("urn:example:ocg:interop-fixture:", serialized)
            self.assertFalse(
                any(relation["kind"] == "compatibility" for relation in imported.document["relations"])
            )
            conformance = validate_document(imported.document)
            self.assertEqual(conformance.errors, [])
            self.assertFalse(conformance.eligibility_evaluated)
            self.assertIsNone(conformance.currently_eligible)

    def test_merged_retrieval_graph_has_three_nonlearned_spaces(self) -> None:
        graph, metadata = build_interoperability_retrieval_graph(
            import_interoperability_fixtures(FIXTURES)
        )
        result = validate_document(graph)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.validated_profiles, ["core", "retrieval"])
        self.assertFalse(result.eligibility_evaluated)
        self.assertIsNone(result.currently_eligible)
        self.assertEqual(result.counts["actions"], 6)
        self.assertEqual(result.counts["artifacts"], 6)
        capabilities = [row for row in graph["nodes"] if row["kind"] == "capability"]
        self.assertEqual(len(graph["representations"]), len(capabilities) * 4)
        spaces = {
            row["embedding"]["space_id"]
            for row in graph["representations"]
            if "embedding" in row
        }
        self.assertEqual(len(spaces), 3)
        self.assertEqual(graph["$schema"], json.loads(SCHEMA_PATH.read_text())["$id"])
        self.assertTrue(metadata["sparse_space"].startswith("urn:example:ocg:space:"))
        self.assertTrue(all(not row["metadata"].get("learned", False) for row in graph["representations"]))
        artifacts = {row["id"]: row for row in graph["artifacts"]}
        for representation in graph["representations"]:
            if "embedding" not in representation:
                continue
            recipe = representation["projection_recipe"]
            self.assertEqual(
                representation["embedding"]["space_id"],
                "urn:example:ocg:space:projection:" + recipe["digest"].split(":", 1)[1],
            )
            self.assertEqual(artifacts[recipe["id"]]["digest"], recipe["digest"])
        sparse_artifact = next(
            row for row in graph["artifacts"] if row["id"].endswith(":token-sparse")
        )
        encoded = sparse_artifact["locators"][0]["uri"].split(",", 1)[1]
        sparse_recipe = json.loads(b64decode(encoded))
        self.assertIsInstance(sparse_recipe["vocabulary"], list)
        self.assertEqual(len(sparse_recipe["vocabulary"]), sparse_recipe["dimensions"])

    @unittest.skipUnless(fts5_available(), "SQLite FTS5 unavailable")
    def test_one_profile_executes_on_reference_and_sqlite_backends(self) -> None:
        graph, metadata = build_interoperability_retrieval_graph(
            import_interoperability_fixtures(FIXTURES)
        )
        result = run_portable_search_bakeoff(graph, metadata)
        self.assertEqual(result["query_count"], 4)
        self.assertEqual(result["backends"], ["reference", "sqlite_fts5"])
        self.assertTrue(result["candidate_only"])
        self.assertFalse(result["learned_embeddings_executed"])
        for backend in result["backends"]:
            self.assertEqual(result["aggregate"][backend]["mean_recall_at_returned_k"], 1.0)
            self.assertEqual(result["aggregate"][backend]["mean_reciprocal_rank"], 1.0)
            self.assertEqual(result["aggregate"][backend]["top1_accuracy"], 1.0)
        self.assertEqual(result["backend_agreement"]["top1_match_rate"], 1.0)
        self.assertGreaterEqual(result["mean_backend_jaccard"], 0.0)
        self.assertLessEqual(result["mean_backend_jaccard"], 1.0)
        self.assertFalse(result["portability_scope"]["full_stack_backend_independence"])
        for query in result["queries"]:
            for backend in result["backends"]:
                receipt = query["bakeoff"]["runs"][backend]["receipt"]
                self.assertTrue(receipt["candidate_only"])
                self.assertFalse(receipt["search_scores_authorize_execution"])

    def test_disjoint_backend_results_do_not_crash_rank_aggregation(self) -> None:
        graph, metadata = build_interoperability_retrieval_graph(
            import_interoperability_fixtures(FIXTURES)
        )
        fake = {
            "runs": {
                "reference": {"receipt": {"returned_ids": ["left"]}},
                "sqlite_fts5": {"receipt": {"returned_ids": ["right"]}},
            },
            "agreement": {
                "jaccard": 0.0,
                "mean_absolute_rank_displacement": None,
                "exact_order_match": False,
                "top1_match": False,
            },
        }
        with patch("aidevobserver_fabric.ocg_interop.run_search_bakeoff", return_value=fake):
            result = run_portable_search_bakeoff(graph, metadata)
        self.assertIsNone(result["backend_agreement"]["mean_absolute_rank_displacement"])
        self.assertEqual(
            result["backend_agreement"]["rank_displacement_observed_query_fraction"],
            0.0,
        )

    def test_cross_format_cases_are_explicit_and_fail_closed(self) -> None:
        cases = interoperability_compatibility_cases(FIXTURES)
        self.assertEqual(len(cases), 6)
        result = run_held_out_benchmark(
            cases,
            benchmark_id="ocg-interoperability-projection-pairs-v0.1",
        ).to_dict()
        self.assertEqual(result["benchmark_id"], "ocg-interoperability-projection-pairs-v0.1")
        self.assertEqual(result["metrics"]["unsafe_safe_edges"], 0)
        self.assertEqual(result["metrics"]["safe_edge_precision"], 1.0)
        self.assertEqual(result["metrics"]["incompatible_recall"], 1.0)
        self.assertEqual(result["metrics"]["exact_accuracy"], 1.0)
        self.assertGreater(result["metrics"]["abstention_rate"], 0.0)
        self.assertTrue(all(row["description"] for row in result["cases"]))

    def test_native_validation_marks_optional_tools_unavailable_without_promoting(self) -> None:
        result = validate_native_fixtures(FIXTURES)
        self.assertEqual(result["validators"]["mcp"]["status"], "passed")
        self.assertIn(result["validators"]["wit"]["status"], {"unavailable", "failed"})
        self.assertFalse(result["all_passed"])

    def test_native_validation_restores_sys_path_and_redacts_failure_paths(self) -> None:
        original = list(sys.path)
        with tempfile.TemporaryDirectory() as temp_dir:
            result = validate_native_fixtures(
                FIXTURES,
                validator_path=Path(temp_dir),
                wasm_tools=Path("/bin/false"),
            )
        self.assertEqual(sys.path, original)
        error = result["validators"]["wit"]["error"]
        self.assertNotIn(str(FIXTURES.resolve()), error)
        self.assertNotIn("/bin/false", error)
        self.assertIn("<fixtures>", error)
        self.assertIn("<wasm-tools>", error)

    @unittest.skipUnless(fts5_available(), "SQLite FTS5 unavailable")
    def test_end_to_end_receipt_and_digest_manifest(self) -> None:
        receipt, documents = run_interoperability_bakeoff(FIXTURES, SCHEMA_PATH)
        self.assertEqual(receipt["merged_graph"]["source_format_count"], 5)
        self.assertTrue(receipt["merged_graph"]["schema_validation"]["valid"])
        self.assertTrue(receipt["merged_graph"]["semantic_validation"]["valid"])
        self.assertFalse(receipt["boundary"]["learned_embeddings_executed"])
        self.assertEqual(receipt["boundary"]["planning_eligibility"], "unknown")
        self.assertEqual(len(documents), 6)
        serialized_inputs = json.dumps(receipt["inputs"], sort_keys=True)
        self.assertNotIn(str(REPO_ROOT), serialized_inputs)
        self.assertEqual(len(receipt["inputs"]["implementation_modules"]), 5)

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            artifact_receipt = write_bakeoff_artifacts(output, receipt, documents)
            manifest = json.loads(Path(artifact_receipt["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["files"]), 7)
            for row in manifest["files"]:
                payload = (output / row["path"]).read_bytes()
                self.assertEqual(row["bytes"], len(payload))
                self.assertEqual(row["digest"], "sha256:" + hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    unittest.main()
