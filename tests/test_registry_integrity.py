from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from aidevobserver_fabric import hybrid, registry


class RegistryIntegrityTests(unittest.TestCase):
    def test_rebuild_is_non_destructive_and_does_not_duplicate_fts_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "registry.sqlite"
            registry.build_db(db)
            con = registry.connect(db)
            with con:
                con.execute(
                    """
                    INSERT INTO primitives VALUES (
                      'user.primitive.v1', 'user primitive', 'Text', 'Text',
                      'candidate', 'R3', '[]', 'inline', 'content_hash', 0,
                      '[]', '[]', '[]', '[]', 'user-defined primitive',
                      'user primitive', '[]'
                    )
                    """
                )
            con.close()

            registry.build_db(db)
            registry.build_db(db)
            con = registry.connect(db)
            try:
                self.assertIsNotNone(registry.get_primitive(con, "user.primitive.v1"))
                duplicate_count = con.execute(
                    """
                    SELECT COUNT(*) FROM primitive_search
                    WHERE primitive_id = 'candidate.csv.profile_columns.v0'
                    """
                ).fetchone()[0]
            finally:
                con.close()
            self.assertEqual(duplicate_count, 1)

    def test_trust_does_not_create_irrelevant_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "registry.sqlite"
            registry.build_db(db)
            con = registry.connect(db)
            try:
                result = hybrid.search(con, "zxqv blorp unrelated", {})
                empty = hybrid.search(con, "", {})
            finally:
                con.close()
            self.assertEqual(result["results"], [])
            self.assertIsNone(result["candidate_bundle"])
            self.assertEqual(empty["results"], [])


if __name__ == "__main__":
    unittest.main()
