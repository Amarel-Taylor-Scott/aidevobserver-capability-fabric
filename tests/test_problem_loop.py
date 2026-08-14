from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from aidevobserver_fabric.problem_loop import (
    LoopConfig,
    load_fixture_map,
    loop_reconcile,
    loop_status,
    request_plan,
    run_loop,
)
from aidevobserver_fabric.problem_sources import DEFAULT_SOURCE_BY_ID


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "examples/problem_observations.fixture.json"


class ProblemLoopTests(unittest.TestCase):
    def test_query_plan_rotates_repositories_and_counterevidence(self) -> None:
        source = DEFAULT_SOURCE_BY_ID["github.operational_issues"]
        first_url, first_query, first_mode = request_plan(source, 0, ("manual reconciliation",))
        second_url, _, _ = request_plan(source, 1, ("manual reconciliation",))
        falsification_url, falsification_query, falsification_mode = request_plan(
            source, 9, ("manual reconciliation",)
        )
        self.assertIn("repo%3Aairbytehq%2Fairbyte", first_url)
        self.assertIn("repo%3Adolibarr%2Fdolibarr", second_url)
        self.assertEqual(first_query, "manual reconciliation")
        self.assertEqual(first_mode, "opportunity")
        self.assertEqual(falsification_mode, "counterevidence")
        self.assertIn(falsification_query.replace(" ", "+"), falsification_url)

    def test_fixture_loop_builds_one_receipted_candidate(self) -> None:
        fixtures = load_fixture_map(FIXTURE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = LoopConfig(
                output_root=root,
                source_ids=(
                    "github.operational_issues",
                    "stackexchange.workflow_questions",
                    "cfpb.complaints",
                ),
                build_limit=3,
            )
            result = run_loop(config, fixture_map=fixtures)
            receipt = result["receipts"][0]
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(receipt["counts"]["observations"], 3)
            self.assertEqual(receipt["counts"]["signals"], 3)
            self.assertEqual(receipt["counts"]["clusters"], 1)
            self.assertEqual(receipt["counts"]["primitive_candidates_built"], 1)
            self.assertEqual(receipt["counts"]["fixture_tests_passed"], 1)
            self.assertFalse(receipt["serves_truth"])
            run_dir = Path(receipt["run_dir"])
            self.assertTrue((run_dir / "manifest.json").is_file())
            candidate_rows = [
                json.loads(line)
                for line in (run_dir / "primitive_candidates.jsonl").read_text(encoding="utf-8").splitlines()
                if line
            ]
            self.assertEqual(len(candidate_rows), 1)
            candidate = candidate_rows[0]
            self.assertEqual(candidate["draft"]["archetype"], "reconciliation")
            self.assertEqual(candidate["draft"]["coverage"]["semantic_compatibility"], "unknown")
            self.assertFalse(candidate["draft"]["coverage"]["execution_authorized"])
            self.assertEqual(candidate["test_receipt"]["scope"], "generated_positive_and_negative_fixtures_only")
            status = loop_status(root)
            self.assertEqual(status["counts"]["execution_receipts"], 1)
            reconciliation = loop_reconcile(root)
            self.assertTrue(reconciliation["clean"])
            self.assertFalse(reconciliation["mutation_performed"])

    def test_source_failure_is_partial_not_an_execution_failure(self) -> None:
        fixtures = load_fixture_map(FIXTURE)
        fixtures["stackexchange.workflow_questions"] = b"not-json"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = LoopConfig(
                output_root=root,
                source_ids=("github.operational_issues", "stackexchange.workflow_questions"),
                build_limit=0,
            )
            result = run_loop(config, fixture_map=fixtures)
            receipt = result["receipts"][0]
            self.assertEqual(receipt["status"], "partial")
            self.assertEqual(receipt["counts"]["sources_succeeded"], 1)
            self.assertEqual(receipt["counts"]["sources_failed"], 1)
            self.assertEqual(receipt["counts"]["fixture_tests_failed"], 0)
            attempts = [
                json.loads(line)
                for line in (Path(receipt["run_dir"]) / "source_attempts.jsonl").read_text(encoding="utf-8").splitlines()
                if line
            ]
            failed = next(row for row in attempts if row["source_id"] == "stackexchange.workflow_questions")
            self.assertEqual(failed["status"], "terminal_failure")
            self.assertIsNotNone(failed["error"]["digest"])

    def test_second_immediate_cycle_respects_source_cadence(self) -> None:
        fixtures = load_fixture_map(FIXTURE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = LoopConfig(
                output_root=root,
                source_ids=("github.operational_issues",),
                build_limit=0,
            )
            result = run_loop(config, fixture_map=fixtures, cycles=2)
            self.assertEqual(result["completed_cycles"], 2)
            self.assertEqual(result["receipts"][0]["counts"]["sources_succeeded"], 1)
            self.assertEqual(result["receipts"][1]["counts"]["sources_skipped"], 1)
            status = loop_status(root)
            self.assertEqual(status["counts"]["observations"], 1)

    def test_evidence_accumulates_across_independent_runs(self) -> None:
        fixtures = load_fixture_map(FIXTURE)
        source_ids = (
            "github.operational_issues",
            "stackexchange.workflow_questions",
            "cfpb.complaints",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = []
            for source_id in source_ids:
                result = run_loop(
                    LoopConfig(
                        output_root=root,
                        source_ids=(source_id,),
                        build_limit=2,
                    ),
                    fixture_map=fixtures,
                )
                receipts.append(result["receipts"][0])
            self.assertEqual(receipts[0]["counts"]["primitive_candidates_built"], 0)
            self.assertEqual(receipts[1]["counts"]["primitive_candidates_built"], 0)
            self.assertEqual(receipts[2]["counts"]["historical_signals_considered"], 2)
            self.assertEqual(receipts[2]["counts"]["primitive_candidates_built"], 1)
            status = loop_status(root)
            self.assertEqual(status["counts"]["observations"], 3)
            self.assertEqual(status["counts"]["execution_receipts"], 1)


if __name__ == "__main__":
    unittest.main()
