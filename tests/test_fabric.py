from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aidevobserver_fabric import fabric, hybrid, registry


class FabricTests(unittest.TestCase):
    def test_registry_builds_seed_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "primitive_search.sqlite"
            counts = registry.build_db(db)
            self.assertGreaterEqual(counts["primitive_records"], 10)
            self.assertGreaterEqual(counts["compatibility_edges"], 4)

    def test_hybrid_search_respects_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "primitive_search.sqlite"
            registry.build_db(db)
            con = registry.connect(db)
            try:
                result = hybrid.search(
                    con,
                    "csv profile rows for warehouse ingestion",
                    {"output_contract": "ColumnProfileSet", "candidate_only": True},
                )
            finally:
                con.close()
            self.assertEqual(result["results"][0]["primitive_id"], "candidate.csv.profile_columns.v0")
            self.assertFalse(result["results"][0]["serves_truth"])
            self.assertEqual(result["candidate_bundle"]["template_role"], "profile_tabular_data")

    def test_rate_bundle_includes_remix_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "primitive_search.sqlite"
            registry.build_db(db)
            con = registry.connect(db)
            try:
                bundle = hybrid.build_bundle(con, "normalize interest rates", "normalize_regulatory_rates").to_dict()
            finally:
                con.close()
            normalize_slot = [slot for slot in bundle["slots"] if slot["slot_id"] == "normalize"][0]
            fits = {candidate["fit"] for candidate in normalize_slot["candidates"]}
            self.assertIn("direct", fits)
            self.assertIn("remix", fits)

    def test_fabric_discovery_is_candidate_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "primitive_search.sqlite"
            data = fabric.build_fabric(db)
            self.assertFalse(data["serves_truth"])
            hits = fabric.discover_services(data, "find reusable primitive search route")
            self.assertTrue(hits)
            self.assertFalse(hits[0]["serves_truth"])
            discovery = fabric.agent_discovery(data)
            self.assertIn("BOUNDARY discovery=awareness authorization=false serves_truth=false", discovery)
            self.assertIn("SVC svc.primitive_search.v0", discovery)


if __name__ == "__main__":
    unittest.main()
