from __future__ import annotations

import unittest

from aidevobserver_fabric.cli import build_parser


class CliTests(unittest.TestCase):
    def test_database_option_works_before_or_after_subcommand(self) -> None:
        parser = build_parser()
        before = parser.parse_args(["--db", "/tmp/before.sqlite", "search", "--query", "email"])
        after = parser.parse_args(["search", "--db", "/tmp/after.sqlite", "--query", "email"])
        self.assertEqual(before.db, "/tmp/before.sqlite")
        self.assertEqual(after.db, "/tmp/after.sqlite")


if __name__ == "__main__":
    unittest.main()
