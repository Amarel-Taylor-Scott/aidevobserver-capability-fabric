from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from aidevobserver_fabric.ocg_conformance import validate_file
from aidevobserver_fabric.primitive_builder import build_candidate, draft_from_problem


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "spec/open-capability-graph/v0.1/schemas/open-capability-graph.schema.json"


class PrimitiveBuilderTests(unittest.TestCase):
    def cluster(self, archetype: str = "reconciliation") -> dict:
        return {
            "cluster_id": "cluster.invoice-reconciliation.1234",
            "archetype": archetype,
            "canonical_statement": "Accounts payable operators manually reconcile invoice exports every day.",
            "actor": "accounts_payable_operator",
            "workflow": "invoice_reconciliation",
            "source_refs": ["https://example.test/issue/1", "https://example.test/complaint/2"],
            "evidence_digests": ["sha256:" + "1" * 64, "sha256:" + "2" * 64],
            "source_classes": ["issue_tracker", "complaint_database"],
            "build_gate": {"eligible": True, "reason": "test_fixture"},
            "score_vector": {"demand": 0.6, "severity": None},
        }

    def test_draft_identity_is_stable_and_candidate_only(self) -> None:
        coverage = {"outcome": "unresolved_gap_candidate", "semantic_compatibility": "unknown"}
        first = draft_from_problem(self.cluster(), coverage=coverage)
        second = draft_from_problem(self.cluster(), coverage=coverage)
        self.assertEqual(first.draft_id, second.draft_id)
        self.assertFalse(first.serves_truth)
        primitive = first.to_primitive_record()
        self.assertFalse(primitive.serves_truth)
        self.assertIn("effects_unknown", primitive.effects)
        self.assertIn("production_execution_receipts_missing", primitive.promotion_blockers)

    def test_workspace_executes_scoped_fixtures_and_conforms_to_ocg(self) -> None:
        coverage = {"outcome": "retrieval_overlap", "semantic_compatibility": "unknown"}
        draft = draft_from_problem(self.cluster(), coverage=coverage)
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_candidate(draft, Path(temporary))
            self.assertEqual(workspace.test_receipt["result"], "pass")
            self.assertFalse(workspace.test_receipt["serves_truth"])
            self.assertEqual(workspace.test_receipt["scope"], "generated_positive_and_negative_fixtures_only")
            for relative in (
                "primitive.json",
                "ocg.json",
                "src/primitive.py",
                "tests/test_contract.py",
                "fixtures/positive.json",
                "fixtures/negative.json",
                "source-evidence.json",
                "receipts/test.json",
                "manifest.json",
            ):
                self.assertTrue((workspace.path / relative).is_file(), relative)
            result = validate_file(workspace.path / "ocg.json", schema_path=SCHEMA)
            self.assertEqual(result.errors, [])
            self.assertTrue(result.valid)
            document = json.loads((workspace.path / "ocg.json").read_text(encoding="utf-8"))
            self.assertEqual(document["status"], "candidate")
            self.assertEqual(document["extensions"]["aidevobserver"]["compatibility"], "unknown")
            self.assertFalse(document["extensions"]["aidevobserver"]["execution_authorized"])

    def test_every_archetype_builds_and_rejects_negative_fixture(self) -> None:
        archetypes = (
            "adapter",
            "reconciliation",
            "validation",
            "aggregation",
            "monitoring",
            "lookup",
            "triage",
            "handoff",
            "extraction",
            "policy",
            "scheduling",
            "sync",
            "workflow",
        )
        with tempfile.TemporaryDirectory() as temporary:
            for archetype in archetypes:
                cluster = self.cluster(archetype)
                cluster["cluster_id"] = "cluster." + archetype
                cluster["workflow"] = archetype + "_workflow"
                draft = draft_from_problem(
                    cluster,
                    coverage={"outcome": "unresolved_gap_candidate", "semantic_compatibility": "unknown"},
                )
                workspace = build_candidate(draft, Path(temporary))
                self.assertEqual(workspace.test_receipt["result"], "pass", archetype)


if __name__ == "__main__":
    unittest.main()
